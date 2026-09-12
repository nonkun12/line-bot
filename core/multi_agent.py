"""Provider-neutral multi-agent orchestration contracts.

This module is intentionally independent from LINE, n8n, and any model vendor.
It provides the management layer needed to run specialized agents in parallel
when their file/resource scopes do not conflict, while serializing conflicting
work. Actual model calls remain the responsibility of each agent adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol, Sequence


class AgentRole(str, Enum):
    """Stable roles used by the management AI."""

    MANAGER = "manager"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    REPAIRER = "repairer"
    INTEGRATOR = "integrator"


@dataclass(frozen=True)
class AgentTask:
    """A bounded unit of work assigned by the management AI."""

    task_id: str
    role: AgentRole
    instruction: str
    resources: frozenset[str] = field(default_factory=frozenset)
    depends_on: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if not self.instruction.strip():
            raise ValueError("instruction is required")
        if any(not resource.strip() for resource in self.resources):
            raise ValueError("resources must contain non-empty names")
        if self.task_id in self.depends_on:
            raise ValueError("task cannot depend on itself")


@dataclass(frozen=True)
class TaskBatch:
    """Tasks that are safe to start concurrently."""

    tasks: tuple[AgentTask, ...]


@dataclass(frozen=True)
class AgentResult:
    """Normalized result returned by an agent adapter."""

    task_id: str
    success: bool
    summary: str = ""
    changed_resources: frozenset[str] = field(default_factory=frozenset)


class AgentExecutor(Protocol):
    """Execution adapter implemented by concrete model/agent runtimes."""

    def execute(self, task: AgentTask) -> AgentResult:
        ...


def resources_conflict(left: AgentTask, right: AgentTask) -> bool:
    """Return True when two tasks may touch the same resource."""

    return bool(left.resources & right.resources)


def plan_batches(tasks: Iterable[AgentTask]) -> tuple[TaskBatch, ...]:
    """Build deterministic parallel batches while respecting dependencies.

    A task may join the current batch only when all of its dependencies were
    placed in earlier batches and it has no resource conflict with another task
    already in that batch. Tasks with the same priority are ordered by task id.
    Cyclic or missing dependencies raise ValueError instead of silently
    producing an unsafe schedule.
    """

    pending = {task.task_id: task for task in tasks}
    if len(pending) == 0:
        return ()

    for task in pending.values():
        missing = [dep for dep in task.depends_on if dep not in pending]
        if missing:
            raise ValueError(f"missing dependency for {task.task_id}: {missing[0]}")

    batches: list[TaskBatch] = []
    completed: set[str] = set()

    while pending:
        ready = [
            task
            for task in pending.values()
            if set(task.depends_on).issubset(completed)
        ]
        if not ready:
            raise ValueError("cyclic task dependencies")

        ready.sort(key=lambda task: (-task.priority, task.task_id))
        selected: list[AgentTask] = []
        for task in ready:
            if all(not resources_conflict(task, other) for other in selected):
                selected.append(task)

        if not selected:
            raise RuntimeError("scheduler could not select a ready task")

        selected_ids = {task.task_id for task in selected}
        batches.append(TaskBatch(tasks=tuple(selected)))
        completed.update(selected_ids)
        for task_id in selected_ids:
            del pending[task_id]

    return tuple(batches)


def default_development_team() -> tuple[AgentRole, ...]:
    """Return the canonical team order without coupling it to implementations."""

    return (
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.REPAIRER,
        AgentRole.INTEGRATOR,
    )
