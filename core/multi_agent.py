"""Provider-neutral multi-agent orchestration contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol

_MAX_TASK_ID_CHARS = 200
_MAX_INSTRUCTION_CHARS = 4000
_MAX_RESOURCES = 8
_MAX_RESOURCE_NAME_CHARS = 200
_MAX_DEPENDENCIES = 8
_MAX_DEPENDENCY_ID_CHARS = 200



class AgentRole(str, Enum):
    MANAGER = "manager"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    DEBUGGER = "debugger"
    REFACTORER = "refactorer"
    REVIEWER = "reviewer"
    REPAIRER = "repairer"  # legacy compatibility; new quality flow uses DEBUGGER/REFACTORER
    INTEGRATOR = "integrator"
    GENERAL = "general"
    VOICE = "voice"
    ENGLISH = "english"
    NEWS = "news"
    STOCKS = "stocks"
    MARKET = "market"
    JOBS = "jobs"
    MUSIC = "music"
    VIDEO = "video"
    WEB = "web"


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    role: AgentRole
    instruction: str
    resources: frozenset[str] = field(default_factory=frozenset)
    depends_on: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id is required")
        if len(self.task_id) > _MAX_TASK_ID_CHARS:
            raise ValueError("task_id exceeds 200 characters")
        if not isinstance(self.role, AgentRole):
            raise ValueError("role must be an AgentRole")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValueError("instruction is required")
        if len(self.instruction) > _MAX_INSTRUCTION_CHARS:
            raise ValueError("instruction exceeds 4000 characters")
        if len(self.resources) > _MAX_RESOURCES:
            raise ValueError("too many resources (max 8)")
        if any(
            not isinstance(resource, str)
            or not resource.strip()
            or len(resource) > _MAX_RESOURCE_NAME_CHARS
            for resource in self.resources
        ):
            raise ValueError("resource names must be non-empty strings <= 200 characters")
        if len(self.depends_on) > _MAX_DEPENDENCIES:
            raise ValueError("too many dependencies (max 8)")
        if any(
            not isinstance(dependency, str)
            or not dependency.strip()
            or len(dependency) > _MAX_DEPENDENCY_ID_CHARS
            for dependency in self.depends_on
        ):
            raise ValueError("dependency ids must be non-empty strings <= 200 characters")
        if self.task_id in self.depends_on:
            raise ValueError("task cannot depend on itself")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValueError("priority must be an integer")
        if not -10 <= self.priority <= 10:
            raise ValueError("priority must be between -10 and 10")


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
        AgentRole.DEBUGGER,
        AgentRole.REFACTORER,
        AgentRole.REVIEWER,
        AgentRole.REPAIRER,
        AgentRole.INTEGRATOR,
    )
