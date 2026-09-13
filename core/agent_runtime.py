"""Bounded execution runtime for the multi-agent development team.

The runtime is provider-neutral: model calls, GitHub, LINE, Slack, and n8n stay
outside this module. It executes bounded development and quality loops and fails
closed on unsafe results.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from .multi_agent import AgentResult, AgentRole, AgentTask, plan_batches


class RuntimeExecutor(Protocol):
    def execute(self, task: AgentTask) -> AgentResult:
        ...


class RepairPlanner(Protocol):
    def repair_task(self, failed_task: AgentTask, result: AgentResult, attempt: int) -> AgentTask:
        ...


class RuntimeExecutionError(RuntimeError):
    """Normalize executor failures while retaining the responsible task id."""

    def __init__(self, task_id: str, cause: Exception) -> None:
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.task_id = task_id


@dataclass(frozen=True)
class RuntimeTaskResult:
    task: AgentTask
    result: AgentResult


@dataclass(frozen=True)
class RuntimeReport:
    completed: tuple[RuntimeTaskResult, ...]
    failed_task_id: str | None = None
    error: str | None = None
    rounds: int = 0
    repair_attempts: int = 0
    integration_ready: bool = False

    @property
    def success(self) -> bool:
        return self.failed_task_id is None and self.error is None


class MultiAgentRuntime:
    """Execute a plan with bounded, currently serialized worktree access."""

    def __init__(self, executors: Mapping[AgentRole, RuntimeExecutor], *, max_workers: int = 1, max_rounds: int = 3) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_workers > 1:
            raise ValueError("max_workers > 1 requires isolated git worktrees")
        if max_rounds < 1 or max_rounds > 3:
            raise ValueError("max_rounds must be between 1 and 3")
        self._executors = dict(executors)
        self._max_workers = max_workers
        self._max_rounds = max_rounds

    def run(self, tasks: Sequence[AgentTask]) -> RuntimeReport:
        """Execute one static plan and fail closed on any unsafe result."""
        try:
            batches = plan_batches(tasks)
        except Exception as exc:
            return RuntimeReport((), error=f"{type(exc).__name__}: {exc}")
        completed: list[RuntimeTaskResult] = []
        for batch in batches:
            missing = [task for task in batch.tasks if task.role not in self._executors]
            if missing:
                task = missing[0]
                return RuntimeReport(tuple(completed), task.task_id, f"missing executor for role: {task.role.value}")
            try:
                results = self._run_batch(batch.tasks)
            except RuntimeExecutionError as exc:
                return RuntimeReport(tuple(completed), exc.task_id, str(exc))
            except Exception as exc:
                task_id = batch.tasks[0].task_id if batch.tasks else None
                return RuntimeReport(tuple(completed), task_id, f"{type(exc).__name__}: {exc}")
            for task, result in results:
                if not result.success:
                    return RuntimeReport(tuple(completed), task.task_id, result.summary or "agent task failed")
                completed.append(RuntimeTaskResult(task, result))
        return RuntimeReport(tuple(completed), rounds=1)

    def run_quality(self, tasks: Sequence[AgentTask]) -> RuntimeReport:
        """Run Implementer -> TEST -> conditional Debug -> Refactor -> TEST -> Review -> Integrator.

        Debugger and Refactorer are real, distinct roles. They are invoked only
        when a quality gate fails, and every successful repair/refactor is gated
        by a mandatory retest. All retries are bounded by ``max_rounds``.
        """
        required = {AgentRole.IMPLEMENTER, AgentRole.TESTER, AgentRole.REVIEWER, AgentRole.INTEGRATOR}
        present = {task.role for task in tasks}
        missing = required - present
        if missing:
            names = ", ".join(sorted(role.value for role in missing))
            return RuntimeReport((), error=f"required development role missing: {names}")

        templates = {task.role: task for task in tasks}
        completed: list[RuntimeTaskResult] = []
        rounds = 0
        quality_attempts = 0

        prefix_roles = (AgentRole.MANAGER, AgentRole.IMPLEMENTER, AgentRole.TESTER)
        prefix = tuple(task for role in prefix_roles if (task := templates.get(role)) is not None)
        prefix_report = self.run(prefix)
        completed.extend(prefix_report.completed)
        rounds = 1
        if not prefix_report.success:
            failed = self._find_failed_task(prefix, prefix_report.failed_task_id)
            return RuntimeReport(tuple(completed), prefix_report.failed_task_id, prefix_report.error, rounds, quality_attempts)

        tester = next(item for item in reversed(completed) if item.task.role is AgentRole.TESTER)
        current_gate = tester
        while not current_gate.result.success:
            if AgentRole.DEBUGGER not in self._executors or AgentRole.REFACTORER not in self._executors:
                return RuntimeReport(tuple(completed), current_gate.task.task_id, "quality gate failed and Debugger/Refactorer executors are required", rounds, quality_attempts)
            if quality_attempts >= self._max_rounds - 1:
                return RuntimeReport(tuple(completed), current_gate.task.task_id, current_gate.result.summary or "quality gate failed", rounds, quality_attempts)
            quality_attempts += 1
            rounds = max(rounds, quality_attempts + 1)
            debug_task = AgentTask(
                task_id=f"debug:{quality_attempts}:{current_gate.task.task_id}",
                role=AgentRole.DEBUGGER,
                instruction=f"Analyze and fix the failure from {current_gate.task.task_id}: {current_gate.result.summary[-2000:]}",
                resources=current_gate.task.resources,
            )
            debug_report = self._run_quality_step(debug_task)
            completed.extend(debug_report.completed)
            if not debug_report.success:
                return RuntimeReport(tuple(completed), debug_report.failed_task_id, debug_report.error, rounds, quality_attempts)

            refactor_task = AgentTask(
                task_id=f"refactor:{quality_attempts}:{debug_task.task_id}",
                role=AgentRole.REFACTORER,
                instruction=f"Refactor the validated fix from {debug_task.task_id} without changing required behavior.",
                resources=current_gate.task.resources,
                depends_on=(debug_task.task_id,),
            )
            refactor_report = self._run_quality_step(refactor_task, completed)
            completed.extend(refactor_report.completed)
            if not refactor_report.success:
                return RuntimeReport(tuple(completed), refactor_report.failed_task_id, refactor_report.error, rounds, quality_attempts)

            retest_task = AgentTask(
                task_id=f"test:{quality_attempts}:retest",
                role=AgentRole.TESTER,
                instruction=f"Mandatory retest after {refactor_task.task_id}.",
                resources=current_gate.task.resources,
            )
            retest_report = self._run_quality_step(retest_task, completed)
            completed.extend(retest_report.completed)
            if not retest_report.success:
                return RuntimeReport(tuple(completed), retest_report.failed_task_id, retest_report.error, rounds, quality_attempts)
            current_gate = retest_report.completed[-1]

        reviewer_template = templates[AgentRole.REVIEWER]
        reviewer_task = AgentTask(
            task_id=reviewer_template.task_id,
            role=reviewer_template.role,
            instruction=reviewer_template.instruction,
            resources=reviewer_template.resources,
            depends_on=(),
        )
        reviewer_report = self._run_quality_step(reviewer_task, completed)
        completed.extend(reviewer_report.completed)
        if not reviewer_report.success:
            reviewer_gate = reviewer_report.completed[-1] if reviewer_report.completed else RuntimeTaskResult(reviewer_task, AgentResult(reviewer_task.task_id, False, reviewer_report.error or "review failed"))
            current_gate = RuntimeTaskResult(
                AgentTask(task_id=reviewer_task.task_id, role=AgentRole.TESTER, instruction="Quality retest after reviewer feedback.", resources=reviewer_task.resources),
                AgentResult(reviewer_task.task_id, False, reviewer_gate.result.summary),
            )
            while not current_gate.result.success:
                if AgentRole.DEBUGGER not in self._executors or AgentRole.REFACTORER not in self._executors:
                    return RuntimeReport(tuple(completed), reviewer_task.task_id, "review gate failed and Debugger/Refactorer executors are required", rounds, quality_attempts)
                if quality_attempts >= self._max_rounds - 1:
                    return RuntimeReport(tuple(completed), reviewer_task.task_id, reviewer_gate.result.summary or "review gate failed", rounds, quality_attempts)
                quality_attempts += 1
                debug_task = AgentTask(f"debug:{quality_attempts}:review", AgentRole.DEBUGGER, f"Fix reviewer failure: {reviewer_gate.result.summary[-2000:]}", reviewer_task.resources)
                debug_report = self._run_quality_step(debug_task)
                completed.extend(debug_report.completed)
                if not debug_report.success:
                    return RuntimeReport(tuple(completed), debug_report.failed_task_id, debug_report.error, rounds, quality_attempts)
                refactor_task = AgentTask(f"refactor:{quality_attempts}:review", AgentRole.REFACTORER, f"Refactor the reviewer fix from {debug_task.task_id} without changing behavior.", reviewer_task.resources)
                refactor_report = self._run_quality_step(refactor_task, completed)
                completed.extend(refactor_report.completed)
                if not refactor_report.success:
                    return RuntimeReport(tuple(completed), refactor_report.failed_task_id, refactor_report.error, rounds, quality_attempts)
                retest_task = AgentTask(f"test:{quality_attempts}:review-retest", AgentRole.TESTER, "Mandatory retest after reviewer fix and refactor.", reviewer_task.resources)
                retest_report = self._run_quality_step(retest_task, completed)
                completed.extend(retest_report.completed)
                if not retest_report.success:
                    return RuntimeReport(tuple(completed), retest_report.failed_task_id, retest_report.error, rounds, quality_attempts)
                rereview_task = AgentTask(f"review:{quality_attempts}:rereview", AgentRole.REVIEWER, "Re-review after successful debug, refactor, and retest.", reviewer_task.resources)
                rereview_report = self._run_quality_step(rereview_task, completed)
                completed.extend(rereview_report.completed)
                if not rereview_report.success:
                    reviewer_gate = rereview_report.completed[-1] if rereview_report.completed else RuntimeTaskResult(rereview_task, AgentResult(rereview_task.task_id, False, rereview_report.error or "review failed"))
                    continue
                current_gate = RuntimeTaskResult(retest_task, AgentResult(retest_task.task_id, True, "retest passed"))
                break

        integrator_template = templates[AgentRole.INTEGRATOR]
        integrator_task = AgentTask(integrator_template.task_id, AgentRole.INTEGRATOR, integrator_template.instruction, integrator_template.resources)
        integrator_report = self._run_quality_step(integrator_task, completed)
        completed.extend(integrator_report.completed)
        if not integrator_report.success:
            return RuntimeReport(tuple(completed), integrator_report.failed_task_id, integrator_report.error, rounds, quality_attempts)
        return RuntimeReport(tuple(completed), rounds=rounds, repair_attempts=quality_attempts, integration_ready=True)

    def _run_quality_step(self, task: AgentTask, completed: Sequence[RuntimeTaskResult] = ()) -> RuntimeReport:
        missing = task.role not in self._executors
        if missing:
            return RuntimeReport(tuple(completed), task.task_id, f"missing executor for role: {task.role.value}")
        report = self.run((task,))
        return report

    def run_development(self, tasks: Sequence[AgentTask], *, repair_planner: RepairPlanner | None = None) -> RuntimeReport:
        """Run Implementer -> Tester -> Reviewer -> Integrator with legacy bounded repair loops."""
        required_roles = {AgentRole.IMPLEMENTER, AgentRole.TESTER, AgentRole.REVIEWER, AgentRole.INTEGRATOR}
        present_roles = {task.role for task in tasks}
        missing_roles = required_roles - present_roles
        if missing_roles:
            missing = ", ".join(sorted(role.value for role in missing_roles))
            return RuntimeReport((), error=f"required development role missing: {missing}")

        integrator_template = next(task for task in tasks if task.role is AgentRole.INTEGRATOR)
        completed: list[RuntimeTaskResult] = []
        current = tuple(tasks)
        repair_attempts = 0

        for round_number in range(1, self._max_rounds + 1):
            report = self.run(current)
            completed.extend(report.completed)
            if not report.success:
                failed = self._find_failed_task(current, report.failed_task_id)
                if failed is None:
                    return RuntimeReport(tuple(completed), report.failed_task_id, report.error, round_number, repair_attempts)
                failed_result = self._failed_result(failed, report.error)
                if failed.role not in (AgentRole.TESTER, AgentRole.REVIEWER):
                    return RuntimeReport(tuple(completed), failed.task_id, report.error, round_number, repair_attempts)
                if repair_planner is None or repair_attempts >= self._max_rounds - 1:
                    return RuntimeReport(tuple(completed), failed.task_id, report.error or "gate failed", round_number, repair_attempts)
                repair_attempts += 1
                try:
                    repair_task = repair_planner.repair_task(failed, failed_result, repair_attempts)
                except Exception as exc:
                    return RuntimeReport(tuple(completed), failed.task_id, f"repair planner failed: {type(exc).__name__}: {exc}", round_number, repair_attempts)
                if repair_task.role is not AgentRole.REPAIRER:
                    return RuntimeReport(tuple(completed), repair_task.task_id, "repair planner returned non-repairer task", round_number, repair_attempts)
                repair_report = self.run((repair_task,))
                completed.extend(repair_report.completed)
                if not repair_report.success:
                    return RuntimeReport(tuple(completed), repair_report.failed_task_id, repair_report.error, round_number, repair_attempts)
                current = self._follow_up_tasks(failed, repair_task, integrator_template, round_number)
                continue

            reviewer = self._latest_role_result(completed, AgentRole.REVIEWER)
            integrator = self._latest_role_result(completed, AgentRole.INTEGRATOR)
            if reviewer is None:
                return RuntimeReport(tuple(completed), error="reviewer gate missing", rounds=round_number, repair_attempts=repair_attempts)
            if integrator is None:
                return RuntimeReport(tuple(completed), error="integrator gate missing", rounds=round_number, repair_attempts=repair_attempts)
            return RuntimeReport(tuple(completed), rounds=round_number, repair_attempts=repair_attempts, integration_ready=True)

        return RuntimeReport(tuple(completed), error="development round limit reached", rounds=self._max_rounds, repair_attempts=repair_attempts)

    def _run_batch(self, tasks: Sequence[AgentTask]) -> list[tuple[AgentTask, AgentResult]]:
        workers = min(self._max_workers, len(tasks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {task.task_id: pool.submit(self._executors[task.role].execute, task) for task in tasks}
            results: list[tuple[AgentTask, AgentResult]] = []
            for task in tasks:
                try:
                    result = futures[task.task_id].result()
                except Exception as exc:
                    raise RuntimeExecutionError(task.task_id, exc) from exc
                if not isinstance(result, AgentResult):
                    raise RuntimeExecutionError(task.task_id, TypeError("executor must return AgentResult"))
                if result.task_id != task.task_id:
                    raise RuntimeExecutionError(task.task_id, ValueError(f"executor returned task_id {result.task_id!r} for {task.task_id!r}"))
                results.append((task, result))
            return results

    @staticmethod
    def _find_failed_task(tasks: Sequence[AgentTask], task_id: str | None) -> AgentTask | None:
        if task_id is None:
            return None
        return next((task for task in tasks if task.task_id == task_id), None)

    @staticmethod
    def _failed_result(task: AgentTask, error: str | None) -> AgentResult:
        return AgentResult(task_id=task.task_id, success=False, summary=error or "gate failed")

    @staticmethod
    def _follow_up_tasks(failed: AgentTask, repair: AgentTask, integrator: AgentTask, round_number: int) -> tuple[AgentTask, ...]:
        if failed.role is AgentRole.TESTER:
            retest_id = f"{failed.task_id}:retest{round_number}"
            review_id = f"{failed.task_id}:review{round_number}"
        elif failed.role is AgentRole.REVIEWER:
            retest_id = f"{failed.task_id}:retest{round_number}"
            review_id = f"{failed.task_id}:rereview{round_number}"
        else:
            raise ValueError("unsupported repair source role")
        gate_id = f"{integrator.task_id}:gate{round_number}"
        retest_instruction = (
            f"Retest after repair task {repair.task_id}."
            if failed.role is AgentRole.TESTER
            else f"Retest after reviewer-requested repair {repair.task_id}."
        )
        review_instruction = (
            f"Review the validated change after {repair.task_id}."
            if failed.role is AgentRole.TESTER
            else f"Re-review after {repair.task_id}."
        )
        return (
            AgentTask(task_id=retest_id, role=AgentRole.TESTER, instruction=retest_instruction, resources=failed.resources),
            AgentTask(task_id=review_id, role=AgentRole.REVIEWER, instruction=review_instruction, resources=failed.resources, depends_on=(retest_id,)),
            AgentTask(task_id=gate_id, role=AgentRole.INTEGRATOR, instruction=f"Run the integration gate after {review_id}.", resources=integrator.resources, depends_on=(review_id,)),
        )

    @staticmethod
    def _latest_role_result(completed: Sequence[RuntimeTaskResult], role: AgentRole) -> RuntimeTaskResult | None:
        for item in reversed(completed):
            if item.task.role is role:
                return item
        return None
