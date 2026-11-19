"""Provider-neutral, fail-closed handoff contracts for agent collaboration.

The handoff layer describes work passed between agents without executing tools,
changing registries, or granting the receiving agent additional permissions.
Runtime mutation remains behind the existing governance and safety gates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class HandoffStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"


@dataclass(frozen=True)
class AgentHandoff:
    """Immutable work packet exchanged between two governed agents."""

    handoff_id: str
    source_agent: str
    target_agent: str
    task: str
    status: HandoffStatus = HandoffStatus.PROPOSED
    context: Mapping[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    safety_constraints: tuple[str, ...] = ()

    def validate(self) -> tuple[str, ...]:
        """Return validation errors; never infer missing permissions."""
        errors: list[str] = []
        if not self.handoff_id.strip():
            errors.append("handoff_id is required")
        if not self.source_agent.strip():
            errors.append("source_agent is required")
        if not self.target_agent.strip():
            errors.append("target_agent is required")
        if self.source_agent.strip() == self.target_agent.strip():
            errors.append("source_agent and target_agent must differ")
        if not self.task.strip():
            errors.append("task is required")
        if not self.safety_constraints:
            errors.append("at least one safety constraint is required")
        return tuple(errors)

    def transition(self, target: HandoffStatus) -> "AgentHandoff":
        """Create the next immutable state using a strict lifecycle."""
        allowed = {
            HandoffStatus.PROPOSED: {HandoffStatus.ACCEPTED, HandoffStatus.REJECTED},
            HandoffStatus.ACCEPTED: {HandoffStatus.COMPLETED, HandoffStatus.REJECTED},
            HandoffStatus.REJECTED: set(),
            HandoffStatus.COMPLETED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(f"invalid handoff transition: {self.status} -> {target}")
        return AgentHandoff(
            handoff_id=self.handoff_id,
            source_agent=self.source_agent,
            target_agent=self.target_agent,
            task=self.task,
            status=target,
            context=dict(self.context),
            allowed_actions=self.allowed_actions,
            safety_constraints=self.safety_constraints,
        )


__all__ = ["AgentHandoff", "HandoffStatus"]
