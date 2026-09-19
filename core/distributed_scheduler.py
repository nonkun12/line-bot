"""Bounded, provider-neutral task scheduling for the multi-agent foundation.

This module deliberately stops at orchestration: it does not edit files, git refs,
or invoke model providers. Resource conflicts are serialized by ``plan_batches``;
independent tasks may execute concurrently when the caller explicitly opts in.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping, Sequence

from .multi_agent import AgentResult, AgentRole, AgentTask, TaskBatch, plan_batches


_MAX_RESULT_SUMMARY_CHARS = 4000
_MAX_CHANGED_RESOURCES = 8
_MAX_RESOURCE_NAME_CHARS = 200


class DistributedExecutionError(RuntimeError):
    """A task executor failed or returned an invalid result."""

    def __init__(self, task_id: str, cause: Exception) -> None:
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.task_id = task_id


@dataclass(frozen=True)
class DistributedRun:
    """Immutable result of one bounded scheduler run."""

    batches: tuple[TaskBatch, ...]
    results: tuple[AgentResult, ...]

    @property
    def success(self) -> bool:
        return all(result.success for result in self.results)


class DistributedTaskScheduler:
    """Schedule dependency-safe tasks with an explicit concurrency bound.

    The scheduler is intentionally provider- and repository-neutral. Callers own
    any isolation required by their executors. A concurrency value above one is
    therefore opt-in and should only be used when executors operate on isolated
    resources (for example separate worktrees).
    """

    def __init__(self, executors: Mapping[AgentRole, object], *, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._executors = dict(executors)
        self._max_workers = max_workers

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def run(self, tasks: Sequence[AgentTask]) -> DistributedRun:
        """Plan and execute all tasks, failing closed on the first bad result."""
        if not tasks:
            raise DistributedExecutionError(
                "<empty>",
                ValueError("at least one task is required"),
            )
        batches = plan_batches(tasks)
        completed: list[AgentResult] = []
        for batch in batches:
            for task in batch.tasks:
                if task.role not in self._executors:
                    raise DistributedExecutionError(
                        task.task_id,
                        LookupError(f"missing executor for role: {task.role.value}"),
                    )
            results = self._run_batch(batch)
            completed.extend(results)
            failed = next((result for result in results if not result.success), None)
            if failed is not None:
                return DistributedRun(batches, tuple(completed))
        return DistributedRun(batches, tuple(completed))

    def _run_batch(self, batch: TaskBatch) -> list[AgentResult]:
        workers = min(self._max_workers, len(batch.tasks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                task.task_id: pool.submit(self._executors[task.role].execute, task)
                for task in batch.tasks
            }
            results: list[AgentResult] = []
            for task in batch.tasks:
                try:
                    result = futures[task.task_id].result()
                except Exception as exc:
                    raise DistributedExecutionError(task.task_id, exc) from exc
                if not isinstance(result, AgentResult):
                    raise DistributedExecutionError(
                        task.task_id,
                        TypeError("executor must return AgentResult"),
                    )
                if not isinstance(result.success, bool):
                    raise DistributedExecutionError(
                        task.task_id,
                        TypeError("AgentResult.success must be bool"),
                    )
                if not isinstance(result.summary, str):
                    raise DistributedExecutionError(
                        task.task_id,
                        TypeError("AgentResult.summary must be str"),
                    )
                if len(result.summary) > _MAX_RESULT_SUMMARY_CHARS:
                    raise DistributedExecutionError(
                        task.task_id,
                        ValueError("AgentResult.summary exceeds 4000 characters"),
                    )
                if not isinstance(result.changed_resources, frozenset) or len(result.changed_resources) > _MAX_CHANGED_RESOURCES or any(
                    not isinstance(resource, str)
                    or not resource.strip()
                    or len(resource) > _MAX_RESOURCE_NAME_CHARS
                    for resource in result.changed_resources
                ):
                    raise DistributedExecutionError(
                        task.task_id,
                        TypeError("AgentResult.changed_resources must be frozenset[str]"),
                    )
                if result.task_id != task.task_id:
                    raise DistributedExecutionError(
                        task.task_id,
                        ValueError(
                            f"executor returned task_id {result.task_id!r} for {task.task_id!r}"
                        ),
                    )
                results.append(result)
            return results
