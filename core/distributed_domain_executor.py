"""Safe adapters for wiring concrete domain handlers into the distributed runtime.

These adapters contain no provider-specific I/O. A caller supplies the actual
handler explicitly; missing handlers remain unregistered and therefore fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .multi_agent import AgentResult, AgentRole, AgentTask

DomainHandler = Callable[[AgentTask], str | AgentResult]


@dataclass(frozen=True)
class HandlerExecutor:
    """Adapt one explicit domain handler to the RuntimeExecutor contract."""

    handler: DomainHandler

    def execute(self, task: AgentTask) -> AgentResult:
        result = self.handler(task)
        if isinstance(result, AgentResult):
            if result.task_id != task.task_id:
                raise ValueError(
                    f"handler returned task_id {result.task_id!r} for {task.task_id!r}"
                )
            return result
        if not isinstance(result, str):
            raise TypeError("domain handler must return AgentResult or str")
        return AgentResult(
            task_id=task.task_id,
            success=True,
            summary=result,
        )


def build_domain_executor(role: AgentRole, handler: DomainHandler) -> tuple[AgentRole, HandlerExecutor]:
    """Create one explicit role/handler pair; no default handler is provided."""
    if not isinstance(role, AgentRole):
        raise TypeError("role must be an AgentRole")
    if not callable(handler):
        raise TypeError("handler must be callable")
    return role, HandlerExecutor(handler)
