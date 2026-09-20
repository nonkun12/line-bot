"""Bounded execution runtime for the multi-agent development team.

The runtime is provider-neutral: model calls, GitHub, LINE, Slack, and n8n stay
outside this module. It executes a bounded development loop and fails closed.
Real file-changing executors can be attached later without changing orchestration.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, TYPE_CHECKING

from .multi_agent import AgentResult, AgentRole, AgentTask, plan_batches

if TYPE_CHECKING:
    from .control_tower import ControlTower, ControlTowerDecision
    from .self_improvement import SelfImprovementEngine
    from .self_improvement_cycle import SelfImprovementCycleResult
    from .self_improvement_handoff import ApprovedImprovementHandoff


class RuntimeExecutor(Protocol):
    def execute(self, task: AgentTask) -> AgentResult:
        ...


class ExecutionSafetyGate(Protocol):
    """Verify the actual worktree change immediately after an executor runs.

    Implementations must inspect the live repository state (diff/SHA/changed
    paths and tests as appropriate) rather than trusting task instructions or
    the executor's declared resources.
    """

    def verify(
        self,
        task: AgentTask,
        result: AgentResult,
        allowed_paths: tuple[str, ...],
    ) -> bool:
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

    def __init__(
        self,
        executors: Mapping[AgentRole, RuntimeExecutor],
        *,
        max_workers: int = 1,
        max_rounds: int = 3,
        feedback_engine: SelfImprovementEngine | None = None,
        control_tower: ControlTower | None = None,
        self_improvement_history_path: str | Path | None = None,
        self_improvement_target_paths: tuple[str, ...] = (),
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_workers > 1:
            raise ValueError("max_workers > 1 requires isolated git worktrees")
        if max_rounds < 1 or max_rounds > 3:
            raise ValueError("max_rounds must be between 1 and 3")
        self._executors = dict(executors)
        self._max_workers = max_workers
        self._max_rounds = max_rounds
        self._feedback_engine = feedback_engine
        self._control_tower = control_tower
        self._self_improvement_history_path = (
            Path(self_improvement_history_path) if self_improvement_history_path is not None else None
        )
        self._self_improvement_target_paths = tuple(self_improvement_target_paths)
        self._execution_safety_gate: ExecutionSafetyGate | None = None
        self._last_control_tower_decision: ControlTowerDecision | None = None
        self._last_self_improvement_cycle: SelfImprovementCycleResult | None = None
        self._last_self_improvement_cycle_error: str | None = None
        self._last_self_improvement_handoffs: tuple[ApprovedImprovementHandoff, ...] = ()
        if feedback_engine is not None and control_tower is not None and control_tower.feedback_engine is not feedback_engine:
            raise ValueError("feedback_engine and control_tower must share the same feedback engine")

    def set_execution_safety_gate(self, gate: ExecutionSafetyGate) -> None:
        """Install the post-execution worktree verification gate."""
        if gate is None:
            raise ValueError("execution safety gate is required")
        self._execution_safety_gate = gate

    @property
    def last_control_tower_decision(self) -> ControlTowerDecision | None:
        """Expose the latest management decision without applying it automatically."""
        return self._last_control_tower_decision

    @property
    def last_self_improvement_cycle(self) -> SelfImprovementCycleResult | None:
        """Expose the latest persisted improvement cycle without applying proposals."""
        return self._last_self_improvement_cycle

    @property
    def last_self_improvement_cycle_error(self) -> str | None:
        """Expose a bounded persistence/analysis error without failing development."""
        return self._last_self_improvement_cycle_error

    @property
    def last_self_improvement_handoffs(self) -> tuple[ApprovedImprovementHandoff, ...]:
        """Expose approved, immutable self-improvement handoffs without executing them."""
        return self._last_self_improvement_handoffs

    def _finalize_development(self, report: RuntimeReport) -> RuntimeReport:
        """Observe one completed development run through the management layer."""
        self._last_control_tower_decision = None
        self._last_self_improvement_cycle = None
        self._last_self_improvement_cycle_error = None
        self._last_self_improvement_handoffs = ()

        if self._self_improvement_history_path is not None:
            # The durable cycle is the single proposal path. Generated
            # proposals are evaluated by the same ControlTower gate rather
            # than creating a parallel management path.
            try:
                from .self_improvement_cycle import run_self_improvement_cycle

                self._last_self_improvement_cycle = run_self_improvement_cycle(
                    report,
                    self._self_improvement_history_path,
                    target_paths=self._self_improvement_target_paths,
                    control_tower=self._control_tower,
                )
                if self._last_self_improvement_cycle.control_tower_decisions:
                    self._last_control_tower_decision = (
                        self._last_self_improvement_cycle.control_tower_decisions[-1]
                    )
                    self._last_self_improvement_handoffs = self._build_approved_handoffs(
                        self._last_self_improvement_cycle.control_tower_decisions
                    )
                elif self._control_tower is None and self._feedback_engine is not None:
                    self._feedback_engine.observe(report)
            except Exception as exc:
                self._last_self_improvement_cycle_error = f"{type(exc).__name__}: {exc}"
                return report

        elif self._control_tower is not None:
            self._last_control_tower_decision = self._control_tower.observe(report)
        elif self._feedback_engine is not None:
            self._feedback_engine.observe(report)

        return report

    def run_self_improvement_cycle(
        self,
        report: RuntimeReport,
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
    ) -> ControlTowerDecision | None:
        """Run one bounded Creator/Critic management cycle for a runtime report.

        This is intentionally separate from repository mutation: an approved
        task is exposed to the existing development pipeline, while this method
        never executes model output or changes files by itself.
        """
        if self._control_tower is None:
            return None
        self._last_control_tower_decision = self._control_tower.observe(
            report,
            objective=objective,
            evidence=evidence,
        )
        self._last_self_improvement_handoffs = self._build_approved_handoffs((self._last_control_tower_decision,))
        return self._last_control_tower_decision

    def _build_approved_handoffs(
        self,
        decisions: Sequence[ControlTowerDecision],
    ) -> tuple[ApprovedImprovementHandoff, ...]:
        """Convert approved decisions into immutable downstream handoffs only."""
        if not self._self_improvement_target_paths:
            return ()
        from .self_improvement_handoff import build_approved_improvement_handoff

        handoffs: list[ApprovedImprovementHandoff] = []
        for decision in decisions:
            try:
                handoffs.append(
                    build_approved_improvement_handoff(
                        decision,
                        self._self_improvement_target_paths,
                    )
                )
            except (PermissionError, TypeError, ValueError):
                continue
        return tuple(handoffs)

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

    def run_development(self, tasks: Sequence[AgentTask], *, repair_planner: RepairPlanner | None = None) -> RuntimeReport:
        """Run Implementer -> Tester -> Reviewer -> Integrator with bounded repair loops."""
        required_roles = {AgentRole.IMPLEMENTER, AgentRole.TESTER, AgentRole.REVIEWER, AgentRole.INTEGRATOR}
        present_roles = {task.role for task in tasks}
        missing_roles = required_roles - present_roles
        if missing_roles:
            missing = ", ".join(sorted(role.value for role in missing_roles))
            return self._finalize_development(RuntimeReport((), error=f"required development role missing: {missing}"))

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
                    return self._finalize_development(RuntimeReport(tuple(completed), report.failed_task_id, report.error, round_number, repair_attempts))
                failed_result = self._failed_result(failed, report.error)
                if failed.role not in (AgentRole.TESTER, AgentRole.REVIEWER):
                    return self._finalize_development(RuntimeReport(tuple(completed), failed.task_id, report.error, round_number, repair_attempts))
                if repair_planner is None or repair_attempts >= self._max_rounds - 1:
                    return self._finalize_development(RuntimeReport(tuple(completed), failed.task_id, report.error or "gate failed", round_number, repair_attempts))
                repair_attempts += 1
                try:
                    repair_task = repair_planner.repair_task(failed, failed_result, repair_attempts)
                except Exception as exc:
                    return self._finalize_development(RuntimeReport(tuple(completed), failed.task_id, f"repair planner failed: {type(exc).__name__}: {exc}", round_number, repair_attempts))
                if repair_task.role is not AgentRole.REPAIRER:
                    return self._finalize_development(RuntimeReport(tuple(completed), repair_task.task_id, "repair planner returned non-repairer task", round_number, repair_attempts))
                repair_report = self.run((repair_task,))
                completed.extend(repair_report.completed)
                if not repair_report.success:
                    return self._finalize_development(RuntimeReport(tuple(completed), repair_report.failed_task_id, repair_report.error, round_number, repair_attempts))
                current = self._follow_up_tasks(failed, repair_task, integrator_template, round_number)
                continue

            reviewer = self._latest_role_result(completed, AgentRole.REVIEWER)
            integrator = self._latest_role_result(completed, AgentRole.INTEGRATOR)
            if reviewer is None:
                return self._finalize_development(RuntimeReport(tuple(completed), error="reviewer gate missing", rounds=round_number, repair_attempts=repair_attempts))
            if integrator is None:
                return self._finalize_development(RuntimeReport(tuple(completed), error="integrator gate missing", rounds=round_number, repair_attempts=repair_attempts))
            return self._finalize_development(RuntimeReport(tuple(completed), rounds=round_number, repair_attempts=repair_attempts, integration_ready=True))

        return self._finalize_development(RuntimeReport(tuple(completed), error="development round limit reached", rounds=self._max_rounds, repair_attempts=repair_attempts))

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
                if self._execution_safety_gate is not None:
                    try:
                        verified = self._execution_safety_gate.verify(
                            task, result, self._self_improvement_target_paths
                        )
                    except Exception as exc:
                        raise RuntimeExecutionError(task.task_id, exc) from exc
                    if not verified:
                        raise RuntimeExecutionError(
                            task.task_id,
                            RuntimeError("execution safety gate rejected actual worktree state"),
                        )
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
