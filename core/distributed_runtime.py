"""Safe coordination boundary for distributed task execution and review.

This module composes the provider-neutral scheduler with the existing Control Tower
without changing the repository-mutating development runtime. Distributed execution
is opt-in and defaults to serialized execution; self-improvement remains a review
signal and never executes an approved task automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .agent_runtime import RuntimeReport, RuntimeTaskResult
from .control_tower import ControlTower, ControlTowerDecision
from .distributed_scheduler import DistributedTaskScheduler
from .multi_agent import AgentRole, AgentTask


@dataclass(frozen=True)
class DistributedCoordinationResult:
    """Execution result plus the management decision, if a tower is attached."""

    report: RuntimeReport
    decision: ControlTowerDecision | None = None


class DistributedDevelopmentCoordinator:
    """Run scheduled tasks and hand only the resulting report to Control Tower."""

    def __init__(
        self,
        executors: Mapping[AgentRole, object],
        *,
        control_tower: ControlTower | None = None,
        max_workers: int = 1,
        isolated: bool = False,
    ) -> None:
        if max_workers > 1 and not isolated:
            raise ValueError("max_workers > 1 requires explicit isolated=True")
        self._scheduler = DistributedTaskScheduler(executors, max_workers=max_workers)
        self._control_tower = control_tower

    @property
    def max_workers(self) -> int:
        return self._scheduler.max_workers

    def run(
        self,
        tasks: Sequence[AgentTask],
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
    ) -> DistributedCoordinationResult:
        """Execute one scheduled plan, then optionally observe it through Control Tower."""
        scheduled = self._scheduler.run(tasks)
        completed = tuple(
            RuntimeTaskResult(task, result)
            for task, result in zip(self._tasks_in_execution_order(tasks, scheduled.batches), scheduled.results)
        )
        report = RuntimeReport(
            completed,
            error=None if scheduled.success else "distributed task failed",
            rounds=1,
            integration_ready=scheduled.success,
        )
        decision = None
        if self._control_tower is not None:
            decision = self._control_tower.observe(
                report,
                objective=objective,
                evidence=evidence,
            )
        return DistributedCoordinationResult(report, decision)

    @staticmethod
    def _tasks_in_execution_order(tasks: Sequence[AgentTask], batches) -> tuple[AgentTask, ...]:
        """Reconstruct scheduler result order without exposing scheduler internals."""
        task_map = {task.task_id: task for task in tasks}
        return tuple(task_map[item.task_id] for batch in batches for item in batch.tasks)
