"""Bounded inter-agent communication contracts.

Messages are coordination data only. They never grant tool permissions or allow
an agent to execute another agent's instructions automatically.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    sender: str
    recipient: str
    message_type: str
    content: str
    correlation_id: str = ""
    reply_to: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    safety_constraints: tuple[str, ...] = ()

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for value, name in (
            (self.message_id, "message_id"),
            (self.sender, "sender"),
            (self.recipient, "recipient"),
            (self.message_type, "message_type"),
            (self.content, "content"),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name} is required")
        if self.sender.strip() == self.recipient.strip():
            errors.append("sender and recipient must differ")
        if not self.safety_constraints:
            errors.append("at least one safety constraint is required")
        return tuple(errors)


class AgentMessageCoordinator:
    """Validate which agents may exchange coordination messages."""

    MANAGEMENT = "management"
    SPECIALISTS = frozenset(
        {
            "general",
            "voice",
            "english",
            "news",
            "stocks",
            "market",
            "jobs",
            "music",
            "video",
        }
    )

    @classmethod
    def _role_key(cls, agent_name: str) -> str:
        value = agent_name.strip().lower()
        if value in {cls.MANAGEMENT, *cls.SPECIALISTS}:
            return value
        if "-" in value:
            prefix, suffix = value.split("-", 1)
            if suffix and prefix in cls.SPECIALISTS:
                return prefix
        return value

    @classmethod
    def validate_route(
        cls,
        sender: str,
        recipient: str,
        *,
        message_type: str | None = None,
        safety_constraints: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        source = cls._role_key(sender)
        target = cls._role_key(recipient)
        errors: list[str] = []
        if not source or not target:
            return ("sender and recipient are required",)
        if sender.strip().lower() == recipient.strip().lower():
            return ("sender and recipient must differ",)
        allowed_sources = {cls.MANAGEMENT, *cls.SPECIALISTS}
        if source not in allowed_sources:
            errors.append("sender is not an approved coordination agent")
        if target not in allowed_sources:
            errors.append("recipient is not an approved coordination agent")
        if (
            source != cls.MANAGEMENT
            and target != cls.MANAGEMENT
            and source in cls.SPECIALISTS
            and target in cls.SPECIALISTS
        ):
            if message_type is not None:
                if message_type != "task_result":
                    errors.append(
                        "specialist-to-specialist messages must be task_result"
                    )
                if "result-only" not in safety_constraints:
                    errors.append(
                        "specialist-to-specialist messages require result-only"
                    )
                if "no-permission-grant" not in safety_constraints:
                    errors.append(
                        "specialist-to-specialist messages require no-permission-grant"
                    )
            return tuple(errors)
        if source == cls.MANAGEMENT and target in cls.SPECIALISTS:
            return tuple(errors)
        if source in cls.SPECIALISTS and target == cls.MANAGEMENT:
            return tuple(errors)
        if not errors:
            errors.append("agent route is not approved")
        return tuple(errors)


class AgentMessageBus:
    """Bounded in-memory mailbox for future agent-to-agent communication."""

    def __init__(self, *, max_messages: int = 200) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self._max_messages = max_messages
        self._queues: dict[str, deque[AgentMessage]] = {}
        self._coordinator = AgentMessageCoordinator()

    def send(self, message: AgentMessage) -> AgentMessage:
        errors = (
            *message.validate(),
            *self._coordinator.validate_route(
                message.sender,
                message.recipient,
                message_type=message.message_type,
                safety_constraints=message.safety_constraints,
            ),
        )
        if len(message.content) > 4000:
            errors = (*errors, "content exceeds 4000 characters")
        if errors:
            raise ValueError("; ".join(dict.fromkeys(errors)))
        queue = self._queues.setdefault(message.recipient.strip(), deque())
        queue.append(message)
        while len(queue) > self._max_messages:
            queue.popleft()
        return message

    def receive(
        self,
        recipient: str,
        *,
        limit: int = 20,
    ) -> tuple[AgentMessage, ...]:
        recipient = recipient.strip()
        if not recipient:
            raise ValueError("recipient is required")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        queue = self._queues.get(recipient)
        if not queue:
            return ()
        messages: list[AgentMessage] = []
        for _ in range(min(limit, len(queue))):
            messages.append(queue.popleft())
        return tuple(messages)

    def peek(
        self,
        recipient: str,
        *,
        limit: int = 20,
    ) -> tuple[AgentMessage, ...]:
        recipient = recipient.strip()
        if not recipient:
            raise ValueError("recipient is required")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        queue = self._queues.get(recipient)
        if not queue:
            return ()
        return tuple(list(queue)[:limit])


__all__ = ["AgentMessage", "AgentMessageBus", "AgentMessageCoordinator"]
