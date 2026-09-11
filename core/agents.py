"""Channel-independent contracts for extensible AI agents."""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class AgentRequest:
    user_id: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResponse:
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Minimal contract implemented by every pluggable agent."""

    name: str
    description: str
    priority: int
    enabled: bool

    def can_handle(self, request: AgentRequest) -> bool:
        ...

    def handle(self, request: AgentRequest) -> AgentResponse:
        ...


class AgentRegistry:
    """Register and resolve agents without coupling channels to agent types."""

    def __init__(self, agents: Sequence[Agent] = ()):
        self._agents: dict[str, Agent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: Agent) -> None:
        name = getattr(agent, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("agent name is required")
        if name in self._agents:
            raise ValueError(f"agent already registered: {name}")
        if not callable(getattr(agent, "can_handle", None)):
            raise TypeError("agent must implement can_handle")
        if not callable(getattr(agent, "handle", None)):
            raise TypeError("agent must implement handle")
        self._agents[name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {name}") from exc

    def resolve_all(self, request: AgentRequest) -> tuple[Agent, ...]:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        matches = [
            agent
            for agent in self._agents.values()
            if bool(getattr(agent, "enabled", True)) and agent.can_handle(request)
        ]
        return tuple(
            sorted(
                matches,
                key=lambda agent: (-getattr(agent, "priority", 0), getattr(agent, "name", "")),
            )
        )

    def resolve(self, request: AgentRequest) -> Agent | None:
        matches = self.resolve_all(request)
        return matches[0] if matches else None

    def names(self) -> tuple[str, ...]:
        return tuple(self._agents)
