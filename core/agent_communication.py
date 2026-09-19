"""Bounded inter-agent communication contracts.

Messages are coordination data only. They never grant tool permissions or allow
an agent to execute another agent's instructions automatically.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping


_MAX_MESSAGE_ID_CHARS = 200
_MAX_AGENT_NAME_CHARS = 100
_MAX_MESSAGE_TYPE_CHARS = 100
_MAX_CONTENT_CHARS = 4000
_MAX_CORRELATION_ID_CHARS = 200
_MAX_REPLY_TO_CHARS = 200
_MAX_CONTEXT_ITEMS = 16
_MAX_CONTEXT_KEY_CHARS = 100
_MAX_CONTEXT_VALUE_CHARS = 1000
_MAX_SAFETY_CONSTRAINTS = 8
_MAX_SAFETY_CONSTRAINT_CHARS = 100


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
        for value, name, limit in (
            (self.message_id, "message_id", _MAX_MESSAGE_ID_CHARS),
            (self.sender, "sender", _MAX_AGENT_NAME_CHARS),
            (self.recipient, "recipient", _MAX_AGENT_NAME_CHARS),
            (self.message_type, "message_type", _MAX_MESSAGE_TYPE_CHARS),
            (self.correlation_id, "correlation_id", _MAX_CORRELATION_ID_CHARS),
        ):
            if isinstance(value, str) and len(value) > limit:
                errors.append(f"{name} exceeds {limit} characters")
        if self.reply_to is not None and (
            not isinstance(self.reply_to, str) or len(self.reply_to) > _MAX_REPLY_TO_CHARS
        ):
            errors.append(f"reply_to exceeds {_MAX_REPLY_TO_CHARS} characters")
        if len(self.content) > _MAX_CONTENT_CHARS:
            errors.append(f"content exceeds {_MAX_CONTENT_CHARS} characters")
        if not self.safety_constraints:
            errors.append("at least one safety constraint is required")
        if len(self.safety_constraints) > _MAX_SAFETY_CONSTRAINTS:
            errors.append(f"too many safety constraints (max {_MAX_SAFETY_CONSTRAINTS})")
        for constraint in self.safety_constraints:
            if not isinstance(constraint, str) or not constraint.strip():
                errors.append("safety constraints must be non-empty strings")
            elif len(constraint) > _MAX_SAFETY_CONSTRAINT_CHARS:
                errors.append(f"safety constraint exceeds {_MAX_SAFETY_CONSTRAINT_CHARS} characters")
        if not isinstance(self.context, Mapping) or len(self.context) > _MAX_CONTEXT_ITEMS:
            errors.append(f"context must contain at most {_MAX_CONTEXT_ITEMS} items")
        elif any(
            not isinstance(key, str)
            or not key.strip()
            or len(key) > _MAX_CONTEXT_KEY_CHARS
            or len(str(value)) > _MAX_CONTEXT_VALUE_CHARS
            for key, value in self.context.items()
        ):
            errors.append("context entries exceed bounded envelope")
        return tuple(errors)


class AgentMessageCoordinator:
    """Validate which agents may exchange coordination messages."""

    MANAGEMENT = "management"
    SPECIALISTS = frozenset({"general", "voice", "english", "news", "stocks", "jobs"})

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
    def validate_route(cls, sender: str, recipient: str) -> tuple[str, ...]:
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
        if source != cls.MANAGEMENT and target != cls.MANAGEMENT and source in cls.SPECIALISTS and target in cls.SPECIALISTS:
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
        errors = (*message.validate(), *self._coordinator.validate_route(message.sender, message.recipient))
        if len(message.content) > 4000:
            errors = (*errors, "content exceeds 4000 characters")
        if errors:
            raise ValueError("; ".join(dict.fromkeys(errors)))
        queue = self._queues.setdefault(message.recipient.strip(), deque())
        queue.append(message)
        while len(queue) > self._max_messages:
            queue.popleft()
        return message

    def receive(self, recipient: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
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

    def peek(self, recipient: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
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
