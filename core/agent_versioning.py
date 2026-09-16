"""Provider-neutral version metadata for individual agents and the integrated AI.

This module records the versioned inputs that define an agent: prompt, model,
tools, memory contract, and configuration. It deliberately does not perform
activation or rollback; callers can use the immutable history to select a
known-good version safely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class AgentVersion:
    agent_name: str
    version: str
    prompt_version: str = "1"
    model_version: str = "1"
    tool_version: str = "1"
    memory_version: str = "1"
    config_version: str = "1"
    status: str = "active"
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.agent_name.strip():
            errors.append("agent_name is required")
        if not self.version.strip():
            errors.append("version is required")
        for name, value in (
            ("prompt_version", self.prompt_version),
            ("model_version", self.model_version),
            ("tool_version", self.tool_version),
            ("memory_version", self.memory_version),
            ("config_version", self.config_version),
        ):
            if not str(value).strip():
                errors.append(f"{name} is required")
        if self.status not in {"active", "candidate", "retired"}:
            errors.append("status must be active, candidate, or retired")
        return tuple(errors)


class AgentVersionRegistry:
    """In-memory history for agents and the integrated AI Manager/Control Tower."""

    def __init__(self, versions: Iterable[AgentVersion] = ()) -> None:
        self._history: dict[str, list[AgentVersion]] = {}
        for version in versions:
            self.register(version)

    def register(self, version: AgentVersion) -> None:
        errors = version.validate()
        if errors:
            raise ValueError("invalid agent version: " + "; ".join(errors))
        history = self._history.setdefault(version.agent_name.strip(), [])
        if any(item.version == version.version for item in history):
            raise ValueError(f"version already registered: {version.agent_name}@{version.version}")
        history.append(version)

    def current(self, agent_name: str) -> AgentVersion | None:
        history = self._history.get(agent_name.strip(), ())
        active = [item for item in history if item.status == "active"]
        return active[-1] if active else None

    def history(self, agent_name: str) -> tuple[AgentVersion, ...]:
        return tuple(self._history.get(agent_name.strip(), ()))

    def rollback_target(self, agent_name: str) -> AgentVersion | None:
        """Return the previous non-retired version; selection only, no activation."""
        history = self._history.get(agent_name.strip(), ())
        active_indexes = [i for i, item in enumerate(history) if item.status == "active"]
        if not active_indexes:
            return None
        current_index = active_indexes[-1]
        for item in reversed(history[:current_index]):
            if item.status != "retired":
                return item
        return None


__all__ = ["AgentVersion", "AgentVersionRegistry"]
