"""Provider-neutral version metadata governed by the shared AgentLifecycle."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .agent_specs import AgentLifecycle


@dataclass(frozen=True)
class AgentVersion:
    """Immutable version snapshot for an agent or the integrated AI."""

    agent_name: str
    version: str
    prompt_version: str = "1"
    model_version: str = "1"
    tool_version: str = "1"
    memory_version: str = "1"
    config_version: str = "1"
    lifecycle: AgentLifecycle = AgentLifecycle.ENABLED
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
        if not isinstance(self.lifecycle, AgentLifecycle):
            errors.append("lifecycle must be an AgentLifecycle")
        return tuple(errors)


class AgentVersionRegistry:
    """In-memory version history governed by the shared lifecycle model."""

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
        if version.lifecycle == AgentLifecycle.ENABLED and any(
            item.lifecycle == AgentLifecycle.ENABLED for item in history
        ):
            raise ValueError(f"active version already registered: {version.agent_name}")
        history.append(version)

    def current(self, agent_name: str) -> AgentVersion | None:
        enabled = [
            item
            for item in self._history.get(str(agent_name).strip(), ())
            if item.lifecycle == AgentLifecycle.ENABLED
        ]
        return enabled[0] if enabled else None

    def history(self, agent_name: str) -> tuple[AgentVersion, ...]:
        return tuple(self._history.get(str(agent_name).strip(), ()))

    def rollback_target(self, agent_name: str) -> AgentVersion | None:
        history = self._history.get(str(agent_name).strip(), ())
        current_indexes = [
            i for i, item in enumerate(history) if item.lifecycle == AgentLifecycle.ENABLED
        ]
        if not current_indexes:
            return None
        for item in reversed(history[: current_indexes[0]]):
            if item.lifecycle != AgentLifecycle.DISABLED:
                return item
        return None


__all__ = ["AgentVersion", "AgentVersionRegistry"]
