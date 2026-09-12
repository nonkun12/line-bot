"""Bounded execution runtime for the multi-agent development team.

The runtime is provider-neutral: model calls, GitHub, LINE, Slack, and n8n stay
outside this module. It executes a bounded development loop and fails closed.
Real file-changing executors can be attached later without changing orchestration.
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
    """Execute a plan with bounded parallelism and a bounded repair loop.

    The default operational mode should use ``max_workers=1`` until executors
    have isolated git worktrees. A failed task never starts a later batch.
    ``run_development`` adds the explicit Tester -> Repairer -> Tester loop and
    requires a successful Reviewer result before the Integrator gate can pass.
    """

    def __init__(
        self,
        executors: Mapping[AgentRole, RuntimeExecutor],
        *,
        max_workers: int = 1,
        max_rounds: int = 3,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_rounds < 1 or max_rounds > 3:
            raise ValueError("max_rounds must be between 1 and 3")
        self._executors = dict(executors)
        self._max_workers = max_workers
        self._max_rounds = max_rounds

    def run(self, tasks: Sequence[AgentTask]) -> RuntimeReport:
        """Execute one static plan; any failed result stops subsequent batches."""
        try:
            batches = plan_batches(tasks)
        except Exception as exc:
            return RuntimeReport((), error=f"{type(exc).__name__}: {exc}")
        completed: list[RuntimeTaskResult] = []
        for batch in batches:
            missing = [task for task in batch.tasks if task.role not in self._executors]
            if missing:
                task = missing[0]
                return RuntimeReport(tuple(completed), task.task_id,
                                     f"missing executor for role: {task.role.value}")
            results = self._run_batch(batch.tasks)
            for task, result in results:
                if not result.success:
                    return RuntimeReport(tuple(completed), task.task_id,
                                         result.summary or "agent task failed")
                completed.append(RuntimeTaskResult(task, result))
        return RuntimeReport(tuple(completed), rounds=1)

    def run_development(
        self,
        tasks: Sequence[AgentTask],
        *,
        repair_planner: RepairPlanner | None = None,
    ) -> RuntimeReport:
        """Run a guarded Implementer/Tester/Reviewer/Repairer development loop.

        This method intentionally does not merge or push anything. Integration
        is represented only by ``integration_ready=True`` after every required
        gate succeeds. A Repairer may create a replacement task, but the total
        number of rounds is fixed by ``max_rounds``.
        """
        completed: list[RuntimeTaskResult] = []
        current = tuple(tasks)
        repair_attempts = 0

        for round_number in range(1, self._max_rounds + 1):
            report = self.run(current)
            completed.extend(report.completed)
            if not report.success:
                failed = self._find_failed_task(current, report.failed_task_id)
                if failed is None:
                    return RuntimeReport(tuple(completed), report.failed_task_id,
                                         report.error, round_number, repair_attempts)
                failed_result = self._failed_result(failed, report.error)
                if failed.role not in (AgentRole.TESTER, AgentRole.REVIEWER):
                    return RuntimeReport(tuple(completed), failed.task_id, report.error,
                                         round_number, repair_attempts)
                if repair_planner is None or repair_attempts >= self._max_rounds - 1:
                    return RuntimeReport(tuple(completed), failed.task_id,
                                         report.error or "gate failed", round_number, repair_attempts)
                repair_attempts += 1
                try:
                    repair_task = repair_planner.repair_task(failed, failed_result, repair_attempts)
                except Exception as exc:
                    return RuntimeReport(tuple(completed), failed.task_id,
                                         f"repair planner failed: {type(exc).__name__}: {exc}",
                                         round_number, repair_attempts)
                if repair_task.role is not AgentRole.REPAIRER:
                    return RuntimeReport(tuple(completed), repair_task.task_id,
                                         "repair planner returned non-repairer task",
                                         round_number, repair_attempts)
                repair_report = self.run((repair_task,))
                completed.extend(repair_report.completed)
                if not repair_report.success:
                    return RuntimeReport(tuple(completed), repair_report.failed_task_id,
                                         repair_report.error, round_number, repair_attempts)
                current = self._follow_up_tasks(failed, repair_task)
                continue

            reviewer = self._latest_role_result(completed, AgentRole.REVIEWER)
            if reviewer is None:
                return RuntimeReport(tuple(completed), error="reviewer gate missing",
                                     rounds=round_number, repair_attempts=repair_attempts)
            # Reviewer success is the only signal this provider-neutral layer accepts.
            return RuntimeReport(tuple(completed), rounds=round_number,
                                 repair_attempts=repair_attempts, integration_ready=True)

        return RuntimeReport(tuple(completed), error="development round limit reached",
                             rounds=self._max_rounds, repair_attempts=repair_attempts)

    def _run_batch(self, tasks: Sequence[AgentTask]) -> list[tuple[AgentTask, AgentResult]]:
        workers = min(self._max_workers, len(tasks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {task.task_id: pool.submit(self._executors[task.role].execute, task)
                       for task in tasks}
            results: list[tuple[AgentTask, AgentResult]] = []
            for task in tasks:
                result = futures[task.task_id].result()
                if not isinstance(result, AgentResult):
                    raise TypeError("executor must return AgentResult")
                if result.task_id != task.task_id:
                    raise ValueError(
                        f"executor returned task_id {result.task_id!r} for {task.task_id!r}"
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
    def _follow_up_tasks(failed: AgentTask, repair: AgentTask) -> tuple[AgentTask, ...]:
        if failed.role is AgentRole.TESTER:
            return (AgentTask(task_id=f"{failed.task_id}:retest", role=AgentRole.TESTER,
                              instruction=f"Retest after repair task {repair.task_id}.",
                              resources=failed.resources, depends_on=()),
                    AgentTask(task_id=f"{failed.task_id}:review", role=AgentRole.REVIEWER,
                              instruction=f"Review the validated change after {repair.task_id}.",
                              resources=failed.resources,
                              depends_on=(f"{failed.task_id}:retest",)))
        if failed.role is AgentRole.REVIEWER:
            return (AgentTask(task_id=f"{failed.task_id}:retest", role=AgentRole.TESTER,
                              instruction=f"Retest after reviewer-requested repair {repair.task_id}.",
                              resources=failed.resources),
                    AgentTask(task_id=f"{failed.task_id}:rereview", role=AgentRole.REVIEWER,
                              instruction=f"Re-review after {repair.task_id}.",
                              resources=failed.resources,
                              depends_on=(f"{failed.task_id}:retest",)))
        raise ValueError("unsupported repair source role")

    @staticmethod
    def _latest_role_result(completed: Sequence[RuntimeTaskResult], role: AgentRole) -> RuntimeTaskResult | None:
        for item in reversed(completed):
            if item.task.role is role:
                return item
        return None
