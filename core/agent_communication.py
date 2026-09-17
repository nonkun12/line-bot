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


class AgentMessageBus:
    """Bounded in-memory mailbox for future agent-to-agent communication."""

    def __init__(self, *, max_messages: int = 200) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self._max_messages = max_messages
        self._queues: dict[str, deque[AgentMessage]] = {}

    def send(self, message: AgentMessage) -> AgentMessage:
        errors = message.validate()
        if errors:
            raise ValueError("; ".join(errors))
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


__all__ = ["AgentMessage", "AgentMessageBus"]
