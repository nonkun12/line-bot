"""Governed direct specialist-to-specialist communication.

This layer sits on top of the bounded AgentMessageBus. It permits only explicit
coordination messages between approved specialist roles and requires a bounded
task correlation plus safety constraints. Messages never grant permissions or
trigger execution by themselves.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_communication import AgentMessage, AgentMessageBus, AgentMessageCoordinator
from .multi_agent import AgentRole


_ALLOWED_MESSAGE_TYPES = frozenset({"request", "response", "observation"})
_BLOCKED_CONTENT_TERMS = (
    "grant permission",
    "grant permissions",
    "elevate privilege",
    "credentials",
    "password",
    "secret",
    ".env",
    "shell command",
    "git push",
    "git commit",
    "deploy",
    "権限を付与",
    "権限を追加",
    "権限をエスカレート",
    "資格情報",
)


class SpecialistCommunicationError(ValueError):
    """Raised when a direct specialist message violates the communication policy."""


class SpecialistCommunicationGateway:
    """Send and receive bounded direct messages between specialist agents."""

    def __init__(
        self,
        message_bus: AgentMessageBus | None = None,
        *,
        max_content_chars: int = 4000,
        max_hops: int = 1,
    ) -> None:
        if max_content_chars < 1 or max_content_chars > 4000:
            raise ValueError("max_content_chars must be between 1 and 4000")
        if max_hops < 1 or max_hops > 2:
            raise ValueError("max_hops must be between 1 and 2")
        self._bus = message_bus or AgentMessageBus()
        self._max_content_chars = max_content_chars
        self._max_hops = max_hops

    def send(
        self,
        *,
        sender: AgentRole | str,
        recipient: AgentRole | str,
        message_id: str,
        message_type: str,
        content: str,
        correlation_id: str,
        task_id: str,
        context: Mapping[str, Any] | None = None,
        safety_constraints: tuple[str, ...] = ("coordination-only", "no-permission-grant"),
    ) -> AgentMessage:
        sender_key = self._specialist_key(sender)
        recipient_key = self._specialist_key(recipient)
        normalized_content = str(content).strip()
        if len(normalized_content) > self._max_content_chars:
            raise SpecialistCommunicationError("content exceeds specialist communication limit")
        if not normalized_content:
            raise SpecialistCommunicationError("content is required")
        if not correlation_id.strip():
            raise SpecialistCommunicationError("correlation_id is required")
        if not task_id.strip():
            raise SpecialistCommunicationError("task_id is required")
        if message_type not in _ALLOWED_MESSAGE_TYPES:
            raise SpecialistCommunicationError("unsupported specialist message type")
        if self._contains_blocked_content(normalized_content):
            raise SpecialistCommunicationError("message contains blocked coordination content")

        raw_context = dict(context or {})
        hop_count = raw_context.get("hop_count", 0)
        if not isinstance(hop_count, int) or isinstance(hop_count, bool) or hop_count < 0:
            raise SpecialistCommunicationError("hop_count must be a non-negative integer")
        if hop_count >= self._max_hops:
            raise SpecialistCommunicationError("specialist message hop limit reached")
        raw_context["task_id"] = task_id.strip()
        raw_context["hop_count"] = hop_count + 1

        errors = AgentMessageCoordinator.validate_route(sender_key, recipient_key)
        if errors:
            raise SpecialistCommunicationError("; ".join(errors))

        message = AgentMessage(
            message_id=message_id.strip(),
            sender=sender_key,
            recipient=recipient_key,
            message_type=message_type,
            content=normalized_content,
            correlation_id=correlation_id.strip(),
            context=raw_context,
            safety_constraints=tuple(
                constraint.strip() for constraint in safety_constraints if constraint.strip()
            ),
        )
        try:
            return self._bus.send(message)
        except ValueError as exc:
            raise SpecialistCommunicationError(str(exc)) from exc

    def receive(
        self,
        recipient: AgentRole | str,
        *,
        limit: int = 20,
    ) -> tuple[AgentMessage, ...]:
        recipient_key = self._specialist_key(recipient)
        try:
            return self._bus.receive(recipient_key, limit=limit)
        except ValueError as exc:
            raise SpecialistCommunicationError(str(exc)) from exc

    @staticmethod
    def _contains_blocked_content(content: str) -> bool:
        lowered = content.casefold()
        return any(term in lowered for term in _BLOCKED_CONTENT_TERMS)

    @staticmethod
    def _specialist_key(role: AgentRole | str) -> str:
        value = role.value if isinstance(role, AgentRole) else str(role).strip().lower()
        if value.startswith("management"):
            raise SpecialistCommunicationError("management AI must use the management channel")
        if value.endswith("-instance"):
            value = value[: -len("-instance")].rstrip("-")
        if value not in AgentMessageCoordinator.SPECIALISTS:
            raise SpecialistCommunicationError("agent is not an approved specialist")
        return value


@dataclass(frozen=True)
class SpecialistCommunicationContext:
    """Task-scoped façade exposed to one specialist without exposing the bus."""

    _gateway: SpecialistCommunicationGateway
    sender: AgentRole
    correlation_id: str
    task_id: str

    def send(
        self,
        *,
        recipient: AgentRole | str,
        message_id: str,
        message_type: str,
        content: str,
        context: Mapping[str, Any] | None = None,
    ) -> AgentMessage:
        return self._gateway.send(
            sender=self.sender,
            recipient=recipient,
            message_id=message_id,
            message_type=message_type,
            content=content,
            correlation_id=self.correlation_id,
            task_id=self.task_id,
            context=context,
        )

    def receive(self, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self._gateway.receive(self.sender, limit=limit)


__all__ = [
    "SpecialistCommunicationContext",
    "SpecialistCommunicationError",
    "SpecialistCommunicationGateway",
]
