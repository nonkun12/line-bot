"""Single governance facade for executable agents, specs, and versions.

The facade keeps the three existing registries consistent without changing
runtime routing. It is intentionally provider-neutral and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_specs import AgentLifecycle, AgentSpec, AgentSpecRegistry
from .agent_versioning import AgentVersion, AgentVersionRegistry
from .agents import Agent, AgentRegistry


@dataclass(frozen=True)
class AgentGovernanceRecord:
    """A read-only view of an agent's executable, specification, and version."""

    name: str
    agent: Agent
    spec: AgentSpec
    version: AgentVersion


class AgentGovernance:
    """Coordinate the existing registries through one deterministic facade."""

    def __init__(
        self,
        agents: AgentRegistry | None = None,
        specs: AgentSpecRegistry | None = None,
        versions: AgentVersionRegistry | None = None,
    ) -> None:
        self.agents = agents or AgentRegistry()
        self.specs = specs or AgentSpecRegistry()
        self.versions = versions or AgentVersionRegistry()

    def register(
        self, agent: Agent, spec: AgentSpec, version: AgentVersion
    ) -> AgentGovernanceRecord:
        name = getattr(agent, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("agent name is required")
        if spec.name != name:
            raise ValueError("agent and spec names must match")
        if version.agent_name != name:
            raise ValueError("agent and version names must match")
        if spec.lifecycle != version.lifecycle:
            raise ValueError("spec and version lifecycles must match")
        if spec.lifecycle != AgentLifecycle.ENABLED:
            raise ValueError("only enabled agents may be registered for runtime use")
        if version.validate():
            raise ValueError("invalid agent version: " + "; ".join(version.validate()))
        self.agents.register(agent)
        try:
            self.specs.register(spec)
            self.versions.register(version)
        except Exception:
            # Registries are intentionally in-memory; callers should treat a
            # failed composite registration as requiring a fresh facade.
            raise
        return AgentGovernanceRecord(name, agent, spec, version)

    def get(self, name: str) -> AgentGovernanceRecord | None:
        normalized = str(name).strip()
        spec = self.specs.get(normalized)
        version = self.versions.current(normalized)
        try:
            agent = self.agents.get(normalized)
        except KeyError:
            agent = None
        if agent is None or spec is None or version is None:
            return None
        if spec.lifecycle != AgentLifecycle.ENABLED or version.lifecycle != AgentLifecycle.ENABLED:
            return None
        return AgentGovernanceRecord(normalized, agent, spec, version)

    def names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.agents.names()
            if self.get(name) is not None
        )


__all__ = ["AgentGovernance", "AgentGovernanceRecord"]
