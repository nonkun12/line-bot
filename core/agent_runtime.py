"""Bounded execution runtime for the multi-agent development team.

The scheduler in :mod:`core.multi_agent` decides *what* may run together.
This module executes those batches through provider-neutral adapters. It keeps
LINE/n8n/model-vendor concerns outside the orchestration layer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping, Protocol

from .multi_agent import AgentResult, AgentRole, AgentTask, plan_batches


class RuntimeExecutor(Protocol):
    """Concrete adapter for one management-AI assigned task."""

    def execute(self, task: AgentTask) -> AgentResult:
        ...


@dataclass(frozen=True)
class RuntimeTaskResult:
    """Result plus the task role for downstream reporting."""

    task: AgentTask
    result: AgentResult


@dataclass(frozen=True)
class RuntimeReport:
    """Immutable execution report for one development run."""

    completed: tuple[RuntimeTaskResult, ...]
    failed_task_id: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.failed_task_id is None and self.error is None


class MultiAgentRuntime:
    """Execute a management-AI plan with bounded parallelism.

    Tasks in a scheduler batch execute concurrently. A later batch starts only
    after every task in the current batch has returned successfully. Any
    exception, missing executor, or malformed result fails closed and prevents
    dependent/later work from starting.
    """

    def __init__(
        self,
        executors: Mapping[AgentRole, RuntimeExecutor],
        *,
        max_workers: int = 4,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._executors = dict(executors)
        self._max_workers = max_workers

    def run(self, tasks: list[AgentTask] | tuple[AgentTask, ...]) -> RuntimeReport:
        batches = plan_batches(tasks)
        completed: list[RuntimeTaskResult] = []

        for batch in batches:
            missing = [
                task for task in batch.tasks if task.role not in self._executors
            ]
            if missing:
                task = missing[0]
                return RuntimeReport(
                    tuple(completed), task.task_id, f"missing executor for role: {task.role.value}"
                )

            workers = min(self._max_workers, len(batch.tasks))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    task.task_id: pool.submit(self._execute_one, task)
                    for task in batch.tasks
                }
                batch_results: list[RuntimeTaskResult] = []
                for task in batch.tasks:
                    future = futures[task.task_id]
                    try:
                        batch_results.append(future.result())
                    except Exception as exc:
                        return RuntimeReport(
                            tuple(completed), task.task_id, f"{type(exc).__name__}: {exc}"
                        )

            completed.extend(batch_results)

        return RuntimeReport(tuple(completed))

    def _execute_one(self, task: AgentTask) -> RuntimeTaskResult:
        result = self._executors[task.role].execute(task)
        if not isinstance(result, AgentResult):
            raise TypeError("executor must return AgentResult")
        if result.task_id != task.task_id:
            raise ValueError(
                f"executor returned task_id {result.task_id!r} for {task.task_id!r}"
            )
        if not result.success:
            raise RuntimeError(result.summary or "agent task failed")
        return RuntimeTaskResult(task=task, result=result)
