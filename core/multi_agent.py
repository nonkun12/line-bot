"""Provider-neutral multi-agent orchestration contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol


class AgentRole(str, Enum):
    MANAGER = "manager"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    REPAIRER = "repairer"
    INTEGRATOR = "integrator"


@dataclass(frozen=True)
class AgentTask:
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
    tasks: tuple[AgentTask, ...]


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    success: bool
    summary: str = ""
    changed_resources: frozenset[str] = field(default_factory=frozenset)


class AgentExecutor(Protocol):
    def execute(self, task: AgentTask) -> AgentResult:
        ...


def resources_conflict(left: AgentTask, right: AgentTask) -> bool:
    return bool(left.resources & right.resources)


def plan_batches(tasks: Iterable[AgentTask]) -> tuple[TaskBatch, ...]:
    pending: dict[str, AgentTask] = {}
    for task in tasks:
        if task.task_id in pending:
            raise ValueError(f"duplicate task_id: {task.task_id}")
        pending[task.task_id] = task
    if not pending:
        return ()
    for task in pending.values():
        missing = [dep for dep in task.depends_on if dep not in pending]
        if missing:
            raise ValueError(f"missing dependency for {task.task_id}: {missing[0]}")

    batches: list[TaskBatch] = []
    completed: set[str] = set()
    while pending:
        ready = [task for task in pending.values() if set(task.depends_on).issubset(completed)]
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
    return (
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.REVIEWER,
        AgentRole.REPAIRER,
        AgentRole.INTEGRATOR,
    )
