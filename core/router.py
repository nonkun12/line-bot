"""Channel-independent agent router backed by AgentRegistry."""

from dataclasses import dataclass

from .agents import AgentRegistry, AgentRequest, AgentResponse


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
        response = agent.handle(request)
        if not isinstance(response, AgentResponse):
            if isinstance(response, str):
                response = AgentResponse(text=response)
            else:
                raise TypeError("agent must return AgentResponse or str")
        return RouteResult(agent=agent.name, response=response)

    def route_to(self, name: str, request: AgentRequest) -> AgentResponse:
        agent = self._registry.get(name)
        response = agent.handle(request)
        if isinstance(response, AgentResponse):
            return response
        if isinstance(response, str):
            return AgentResponse(text=response)
        raise TypeError("agent must return AgentResponse or str")
