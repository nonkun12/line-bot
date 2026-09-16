"""Fail-closed coordination for safe Developer/Debug/Test handoffs."""
from __future__ import annotations

from dataclasses import dataclass

from .agent_handoff import AgentHandoff, HandoffStatus


@dataclass(frozen=True)
class HandoffDecision:
    """Deterministic coordinator result; no tools or permissions are executed."""

    accepted: bool
    handoff: AgentHandoff | None = None
    errors: tuple[str, ...] = ()


class AgentHandoffCoordinator:
    """Validate and route collaboration packets without granting capabilities."""

    _ALLOWED_ROUTES = {
        "developer": frozenset({"debug", "test"}),
        "debug": frozenset({"developer", "test"}),
        "test": frozenset({"developer", "debug"}),
    }

    def submit(self, handoff: AgentHandoff) -> HandoffDecision:
        """Accept only valid, proposed packets on an approved agent route."""
        errors = list(handoff.validate())
        source = handoff.source_agent.strip().lower()
        target = handoff.target_agent.strip().lower()
        if source not in self._ALLOWED_ROUTES:
            errors.append("source_agent is not an approved collaboration agent")
        elif target not in self._ALLOWED_ROUTES[source]:
            errors.append("source_agent and target_agent route is not approved")
        if handoff.status is not HandoffStatus.PROPOSED:
            errors.append("handoff must be proposed before submission")
        if errors:
            return HandoffDecision(False, errors=tuple(errors))
        return HandoffDecision(True, handoff=handoff.transition(HandoffStatus.ACCEPTED))

    def complete(self, handoff: AgentHandoff) -> HandoffDecision:
        """Complete only an accepted handoff that still passes validation."""
        errors = list(handoff.validate())
        if handoff.status is not HandoffStatus.ACCEPTED:
            errors.append("handoff must be accepted before completion")
        if errors:
            return HandoffDecision(False, errors=tuple(errors))
        return HandoffDecision(True, handoff=handoff.transition(HandoffStatus.COMPLETED))


__all__ = ["AgentHandoffCoordinator", "HandoffDecision"]
