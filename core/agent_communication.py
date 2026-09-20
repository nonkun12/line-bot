"""Bounded inter-agent communication contracts.

Messages are coordination data only. They never grant tool permissions or allow
an agent to execute another agent's instructions automatically.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from types import MappingProxyType
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
_MAX_MESSAGES_PER_MAILBOX = 200

_ALLOWED_CONTEXT_KEYS = frozenset({"task_id", "success", "changed_resources"})


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
    safety_constraints: frozenset[str] | tuple[str, ...] = field(
        default_factory=frozenset
    )

    def __post_init__(self) -> None:
        errors = self.validate()
        if errors:
            raise ValueError("; ".join(dict.fromkeys(errors)))

        constraints = frozenset(self.safety_constraints)
        context = MappingProxyType(dict(self.context))
        object.__setattr__(self, "safety_constraints", constraints)
        object.__setattr__(self, "context", context)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for value, name, limit in (
            (self.message_id, "message_id", _MAX_MESSAGE_ID_CHARS),
            (self.sender, "sender", _MAX_AGENT_NAME_CHARS),
            (self.recipient, "recipient", _MAX_AGENT_NAME_CHARS),
            (self.message_type, "message_type", _MAX_MESSAGE_TYPE_CHARS),
            (self.correlation_id, "correlation_id", _MAX_CORRELATION_ID_CHARS),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name} is required")
            elif len(value) > limit:
                errors.append(f"{name} exceeds {limit} characters")
        if not isinstance(self.content, str) or not self.content.strip():
            errors.append("content is required")
        elif len(self.content) > _MAX_CONTENT_CHARS:
            errors.append(f"content exceeds {_MAX_CONTENT_CHARS} characters")

        if self.reply_to is not None and (
            not isinstance(self.reply_to, str) or len(self.reply_to) > _MAX_REPLY_TO_CHARS
        ):
            errors.append(f"reply_to exceeds {_MAX_REPLY_TO_CHARS} characters")

        if isinstance(self.safety_constraints, str):
            errors.append("safety_constraints must not be a string")
        else:
            try:
                constraints = tuple(self.safety_constraints)
            except TypeError:
                errors.append("safety_constraints must be an iterable of strings")
            else:
                if not constraints:
                    errors.append("at least one safety constraint is required")
                if len(constraints) > _MAX_SAFETY_CONSTRAINTS:
                    errors.append(
                        f"too many safety constraints (max {_MAX_SAFETY_CONSTRAINTS})"
                    )
                for constraint in constraints:
                    if not isinstance(constraint, str) or not constraint.strip():
                        errors.append("safety constraints must be non-empty strings")
                    elif len(constraint) > _MAX_SAFETY_CONSTRAINT_CHARS:
                        errors.append(
                            "safety constraint exceeds "
                            f"{_MAX_SAFETY_CONSTRAINT_CHARS} characters"
                        )

        if not isinstance(self.context, Mapping):
            errors.append("context must be a mapping")
        elif len(self.context) > _MAX_CONTEXT_ITEMS:
            errors.append(f"context must contain at most {_MAX_CONTEXT_ITEMS} items")
        else:
            for key, value in self.context.items():
                if (
                    not isinstance(key, str)
                    or not key.strip()
                    or len(key) > _MAX_CONTEXT_KEY_CHARS
                ):
                    errors.append("context key exceeds bounded envelope")
                    continue
                if key not in _ALLOWED_CONTEXT_KEYS:
                    errors.append(f"context key is not allowed: {key}")
                    continue
                if len(str(value)) > _MAX_CONTEXT_VALUE_CHARS:
                    errors.append("context value exceeds bounded envelope")
                    continue
                if key == "task_id" and (
                    not isinstance(value, str) or not value.strip()
                ):
                    errors.append("context task_id must be a non-empty string")
                elif key == "success" and not isinstance(value, bool):
                    errors.append("context success must be bool")
                elif key == "changed_resources":
                    if not isinstance(value, (list, tuple, frozenset)):
                        errors.append("context changed_resources must be a collection")
                    elif len(value) > 8 or any(
                        not isinstance(item, str) or not item.strip() or len(item) > 200
                        for item in value
                    ):
                        errors.append("context changed_resources exceeds bounds")
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
    KNOWN_AGENTS = frozenset({MANAGEMENT, *SPECIALISTS})
    RESULT_MESSAGE_TYPE = "task_result"
    RESULT_CONSTRAINTS = frozenset({"result-only", "no-permission-grant"})

    @classmethod
    def _role_key(cls, agent_name: str) -> str:
        if not isinstance(agent_name, str):
            return ""
        return agent_name.strip().lower()

    @classmethod
    def canonical_agent(cls, agent_name: str) -> str:
        key = cls._role_key(agent_name)
        if key not in cls.KNOWN_AGENTS:
            raise ValueError("agent is not an approved coordination endpoint")
        return key

    @classmethod
    def validate_route(
        cls,
        sender: str,
        recipient: str,
        *,
        message_type: str,
        safety_constraints: frozenset[str] | tuple[str, ...],
    ) -> tuple[str, ...]:
        source = cls._role_key(sender)
        target = cls._role_key(recipient)
        errors: list[str] = []

        if source not in cls.KNOWN_AGENTS:
            errors.append("sender is not an approved coordination agent")
        if target not in cls.KNOWN_AGENTS:
            errors.append("recipient is not an approved coordination agent")
        if not isinstance(message_type, str) or not message_type.strip():
            errors.append("message_type is required")
        if isinstance(safety_constraints, str):
            errors.append("safety_constraints must not be a string")
            constraints = frozenset()
        else:
            try:
                constraints = frozenset(safety_constraints)
            except TypeError:
                errors.append("safety_constraints must be iterable")
                constraints = frozenset()

        if source == target and source in cls.KNOWN_AGENTS:
            errors.append("sender and recipient must differ")

        if (
            source in cls.SPECIALISTS
            and target in cls.SPECIALISTS
            and source != target
        ):
            if message_type != cls.RESULT_MESSAGE_TYPE:
                errors.append("specialist-to-specialist messages must be task_result")
            if constraints != cls.RESULT_CONSTRAINTS:
                errors.append(
                    "specialist-to-specialist messages require exactly "
                    "result-only and no-permission-grant"
                )
            return tuple(dict.fromkeys(errors))

        if source in cls.SPECIALISTS and target == cls.MANAGEMENT:
            if message_type != cls.RESULT_MESSAGE_TYPE:
                errors.append("specialist-to-management messages must be task_result")
            if constraints != cls.RESULT_CONSTRAINTS:
                errors.append(
                    "specialist-to-management messages require exactly "
                    "result-only and no-permission-grant"
                )
            return tuple(dict.fromkeys(errors))

        if source == cls.MANAGEMENT and target in cls.SPECIALISTS:
            errors.append("management-to-specialist messages are not approved")
            return tuple(dict.fromkeys(errors))

        if not errors:
            errors.append("agent route is not approved")
        return tuple(dict.fromkeys(errors))


class AgentMessageEndpoint:
    """Identity-bound endpoint issued only by an AgentMessageBus."""

    def __init__(self, bus: "AgentMessageBus", identity: str, token: object) -> None:
        self._bus = bus
        self._identity = identity
        self._token = token

    @property
    def identity(self) -> str:
        return self._identity

    def send(
        self,
        recipient: str,
        *,
        message_id: str,
        message_type: str,
        content: str,
        correlation_id: str = "",
        reply_to: str | None = None,
        context: Mapping[str, Any] | None = None,
        safety_constraints: frozenset[str] | tuple[str, ...] = (),
    ) -> AgentMessage:
        message = AgentMessage(
            message_id=message_id,
            sender=self._identity,
            recipient=recipient,
            message_type=message_type,
            content=content,
            correlation_id=correlation_id,
            reply_to=reply_to,
            context=context or {},
            safety_constraints=safety_constraints,
        )
        return self._bus._send(self._token, message)

    def receive(self, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self._bus._receive(self._identity, limit=limit)

    def peek(self, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self._bus._peek(self._identity, limit=limit)


class AgentMailboxView:
    """Read-only mailbox view; it cannot send messages."""

    def __init__(self, bus: "AgentMessageBus", identity: str) -> None:
        self._bus = bus
        self._identity = identity

    @property
    def identity(self) -> str:
        return self._identity

    def receive(self, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self._bus._receive(self._identity, limit=limit)

    def peek(self, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self._bus._peek(self._identity, limit=limit)


class AgentMessageBus:
    """Bounded mailbox with identity-bound senders and canonical recipient keys."""

    def __init__(self, *, max_messages: int = _MAX_MESSAGES_PER_MAILBOX) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self._max_messages = min(max_messages, _MAX_MESSAGES_PER_MAILBOX)
        self._queues: dict[str, deque[AgentMessage]] = {}
        self._coordinator = AgentMessageCoordinator()
        self._endpoint_tokens: dict[object, str] = {}

    def endpoint(self, identity: str) -> AgentMessageEndpoint:
        canonical = self._coordinator.canonical_agent(identity)
        token = object()
        self._endpoint_tokens[token] = canonical
        return AgentMessageEndpoint(self, canonical, token)

    def mailbox(self, identity: str) -> AgentMailboxView:
        canonical = self._coordinator.canonical_agent(identity)
        return AgentMailboxView(self, canonical)

    def _send(self, token: object, message: AgentMessage) -> AgentMessage:
        identity = self._endpoint_tokens.get(token)
        if identity is None:
            raise ValueError("unrecognized message endpoint")
        if message.sender != identity:
            raise ValueError("endpoint identity does not match message sender")

        errors = (
            *message.validate(),
            *self._coordinator.validate_route(
                message.sender,
                message.recipient,
                message_type=message.message_type,
                safety_constraints=message.safety_constraints,
            ),
        )
        if errors:
            raise ValueError("; ".join(dict.fromkeys(errors)))

        recipient = self._coordinator.canonical_agent(message.recipient)
        queue = self._queues.setdefault(recipient, deque())
        queue.append(message)
        while len(queue) > self._max_messages:
            queue.popleft()
        return message

    def _receive(self, recipient: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        recipient = self._coordinator.canonical_agent(recipient)
        if limit < 1:
            raise ValueError("limit must be >= 1")
        queue = self._queues.get(recipient)
        if not queue:
            return ()
        messages: list[AgentMessage] = []
        for _ in range(min(limit, len(queue))):
            messages.append(queue.popleft())
        return tuple(messages)

    def _peek(self, recipient: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        recipient = self._coordinator.canonical_agent(recipient)
        if limit < 1:
            raise ValueError("limit must be >= 1")
        queue = self._queues.get(recipient)
        if not queue:
            return ()
        return tuple(list(queue)[:limit])


__all__ = [
    "AgentMessage",
    "AgentMessageBus",
    "AgentMessageCoordinator",
    "AgentMessageEndpoint",
    "AgentMailboxView",
]
