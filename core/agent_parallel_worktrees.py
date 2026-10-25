"""Bounded parallel execution for tasks in independent Git worktrees.

This is an opt-in primitive. It never merges worker branches or deploys changes;
every worktree is retained for review, including failed work, and later dependency
batches are skipped after any failure.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol, Sequence

from .agent_worktree import IsolatedWorktree, IsolatedWorktreeManager, WorktreeError
from .multi_agent import AgentResult, AgentTask, plan_batches


class WorktreeTaskExecutor(Protocol):
    def execute_in_worktree(self, task: AgentTask, worktree_path: Path) -> AgentResult:
        """Run the task only inside the supplied isolated worktree."""
        ...


class WorktreeSafetyGate(Protocol):
    def verify(self, task: AgentTask, result: AgentResult, worktree_path: Path) -> bool:
        """Inspect actual worktree changes and reject out-of-scope or unsafe results."""
        ...


@dataclass(frozen=True)
class IsolatedTaskOutcome:
    task: AgentTask
    result: AgentResult
    worktree: IsolatedWorktree | None
    error: str | None = None


@dataclass(frozen=True)
class IsolatedBatchReport:
    outcomes: tuple[IsolatedTaskOutcome, ...]
    failed_task_id: str | None = None
    error: str | None = None
    batches_completed: int = 0

    @property
    def success(self) -> bool:
        return self.failed_task_id is None and self.error is None


class IsolatedParallelBatchRunner:
    """Run dependency/resource-safe batches with a hard worker cap of four.

    Worktrees are intentionally not cleaned up automatically: changes must be
    reviewed and explicitly preserved/discarded by a separate workflow.
    """

    def __init__(
        self,
        worktree_manager: IsolatedWorktreeManager,
        executor: WorktreeTaskExecutor,
        safety_gate: WorktreeSafetyGate,
        *,
        base_ref: str,
        max_workers: int = 2,
    ) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or not 1 <= max_workers <= 4:
            raise ValueError("max_workers must be between 1 and 4")
        if not isinstance(base_ref, str) or not base_ref.strip():
            raise ValueError("base_ref is required")
        if safety_gate is None:
            raise ValueError("worktree safety gate is required")
        self._manager = worktree_manager
        self._executor = executor
        self._safety_gate = safety_gate
        self._base_ref = base_ref
        self._max_workers = max_workers
        self._create_lock = Lock()

    def run(self, tasks: Sequence[AgentTask]) -> IsolatedBatchReport:
        try:
            batches = plan_batches(tasks)
        except Exception as exc:
            return IsolatedBatchReport((), error=f"{type(exc).__name__}: {exc}")
        outcomes: list[IsolatedTaskOutcome] = []
        completed_batches = 0
        for batch in batches:
            worker_count = min(self._max_workers, len(batch.tasks))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = {
                    task.task_id: pool.submit(self._execute_one, task)
                    for task in batch.tasks
                }
                batch_outcomes: list[IsolatedTaskOutcome] = []
                for task in batch.tasks:
                    try:
                        outcome = futures[task.task_id].result()
                    except Exception as exc:
                        outcome = IsolatedTaskOutcome(
                            task=task,
                            result=AgentResult(task.task_id, False, "isolated worker failed"),
                            worktree=None,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    batch_outcomes.append(outcome)
            outcomes.extend(batch_outcomes)
            failed = next((item for item in batch_outcomes if not item.result.success or item.error), None)
            if failed is not None:
                return IsolatedBatchReport(
                    tuple(outcomes),
                    failed_task_id=failed.task.task_id,
                    error=failed.error or failed.result.summary or "isolated task failed",
                    batches_completed=completed_batches,
                )
            completed_batches += 1
        return IsolatedBatchReport(tuple(outcomes), batches_completed=completed_batches)

    def _execute_one(self, task: AgentTask) -> IsolatedTaskOutcome:
        worktree: IsolatedWorktree | None = None
        try:
            # Registry mutations are serialized; actual model/tool work is not.
            with self._create_lock:
                worktree = self._manager.create(task.task_id, self._base_ref)
            result = self._executor.execute_in_worktree(task, worktree.path)
            if not isinstance(result, AgentResult):
                raise TypeError("executor must return AgentResult")
            if result.task_id != task.task_id:
                raise ValueError(f"executor returned task_id {result.task_id!r} for {task.task_id!r}")
            if not result.success:
                return IsolatedTaskOutcome(task, result, worktree)
            if not self._safety_gate.verify(task, result, worktree.path):
                return IsolatedTaskOutcome(
                    task,
                    AgentResult(task.task_id, False, "worktree safety gate rejected actual changes"),
                    worktree,
                )
            return IsolatedTaskOutcome(task, result, worktree)
        except Exception as exc:
            return IsolatedTaskOutcome(
                task,
                AgentResult(task.task_id, False, f"{type(exc).__name__}: {exc}"),
                worktree,
                error=f"{type(exc).__name__}: {exc}",
            )
