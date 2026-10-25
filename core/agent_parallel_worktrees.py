"""Bounded parallel execution for tasks in independent Git worktrees.

This is an opt-in primitive. It never merges worker branches or deploys changes;
every worktree is retained for review, including failed work, and later dependency
batches are skipped after any failure.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Lock
from typing import Protocol, Sequence

from .agent_worktree import IsolatedWorktree, IsolatedWorktreeManager
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
    changed_paths: tuple[str, ...] = ()


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
            # Detect undeclared overlapping edits from the actual Git status, not
            # only the resource names supplied by task planners.
            owners: dict[str, str] = {}
            collision: tuple[str, str, str] | None = None
            for item in batch_outcomes:
                if not item.result.success or item.error:
                    continue
                for path in item.changed_paths:
                    prior = next(
                        (
                            (owner, prior_path)
                            for prior_path, owner in owners.items()
                            if owner != item.task.task_id
                            and (
                                path == prior_path
                                or path.startswith(prior_path + "/")
                                or prior_path.startswith(path + "/")
                            )
                        ),
                        None,
                    )
                    if prior is not None:
                        collision = (prior[0], item.task.task_id, path)
                        break
                    owners[path] = item.task.task_id
                if collision:
                    break
            if collision:
                first, second, path = collision
                batch_outcomes = [
                    IsolatedTaskOutcome(
                        item.task,
                        AgentResult(item.task.task_id, False, f"actual changed-path conflict with {first}: {path}")
                        if item.task.task_id == second else item.result,
                        item.worktree,
                        f"actual changed-path conflict with {first}: {path}" if item.task.task_id == second else item.error,
                        item.changed_paths,
                    )
                    for item in batch_outcomes
                ]
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
            # Every task starts from the same immutable base ref. Until a
            # separately reviewed integration mechanism exists, a later
            # dependency batch must not run against stale source after an
            # earlier batch produced edits.
            if completed_batches < len(batches) and any(item.changed_paths for item in batch_outcomes):
                return IsolatedBatchReport(
                    tuple(outcomes),
                    failed_task_id=None,
                    error=(
                        "dependency batch produced unintegrated changes; "
                        "refusing to run later tasks from stale base_ref"
                    ),
                    batches_completed=completed_batches,
                )
        return IsolatedBatchReport(tuple(outcomes), batches_completed=completed_batches)

    @staticmethod
    def _changed_paths(worktree_path: Path) -> tuple[str, ...]:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            check=True,
            capture_output=True,
            timeout=15,
        )
        fields = result.stdout.split(b"\0")
        paths: set[str] = set()
        index = 0
        while index < len(fields):
            field = fields[index]
            index += 1
            if not field:
                continue
            if len(field) < 4 or field[2:3] != b" ":
                raise ValueError("could not safely parse Git worktree status")
            status = field[:2]
            path = field[3:].decode("utf-8", errors="strict")
            paths.add(path)
            # Porcelain v1 -z emits a second NUL-delimited path for rename/copy.
            if b"R" in status or b"C" in status:
                if index >= len(fields) or not fields[index]:
                    raise ValueError("incomplete rename/copy entry in Git status")
                paths.add(fields[index].decode("utf-8", errors="strict"))
                index += 1
        return tuple(sorted(paths))

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
            changed_paths = self._changed_paths(worktree.path)
            return IsolatedTaskOutcome(task, result, worktree, changed_paths=changed_paths)
        except Exception as exc:
            return IsolatedTaskOutcome(
                task,
                AgentResult(task.task_id, False, f"{type(exc).__name__}: {exc}"),
                worktree,
                error=f"{type(exc).__name__}: {exc}",
            )
