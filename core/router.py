"""Channel-independent agent router backed by AgentRegistry."""

from dataclasses import dataclass
from typing import Mapping

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse


@dataclass(frozen=True)
class RouteResult:
    agent: str | None
    response: AgentResponse | None = None


class AgentRouter:
    """Resolve and execute any registered agent without a hardcoded agent list."""

    def __init__(self, registry: AgentRegistry):
        if not isinstance(registry, AgentRegistry):
            raise TypeError("registry must be an AgentRegistry")
        self._registry = registry

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    def route(self, request: AgentRequest) -> RouteResult:
        agent = self._registry.resolve(request)
        if agent is None:
            return RouteResult(agent=None)
        return RouteResult(agent=agent.name, response=agent.handle(request))

    def route_to(self, name: str, request: AgentRequest) -> AgentResponse:
        agent = self._registry.get(name)
        return agent.handle(request)
