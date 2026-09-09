from dataclasses import dataclass

import pytest

from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.router import AgentRouter, RouteResult


@dataclass
class FakeAgent:
    name: str
    description: str
    keyword: str
    priority: int = 0
    enabled: bool = True
    return_text: bool = False

    def can_handle(self, request: AgentRequest) -> bool:
        return self.keyword in request.message

    def handle(self, request: AgentRequest) -> AgentResponse | str:
        text = f"handled by {self.name}"
        return text if self.return_text else AgentResponse(text=text)


def test_router_resolves_and_executes_registered_agent():
    registry = AgentRegistry([FakeAgent("weather", "Weather", "天気")])
    result = AgentRouter(registry).route(AgentRequest("u1", "東京の天気"))

    assert result == RouteResult(
        agent="weather",
        response=AgentResponse(text="handled by weather"),
    )


def test_router_returns_empty_result_for_unhandled_request():
    registry = AgentRegistry([FakeAgent("news", "News", "ニュース")])

    assert AgentRouter(registry).route(AgentRequest("u1", "こんにちは")) == RouteResult(
        agent=None,
        response=None,
    )


def test_router_can_execute_explicit_future_agent():
    registry = AgentRegistry()
    registry.register(FakeAgent("travel", "Travel", "旅行"))

    result = AgentRouter(registry).route_to(
        "travel",
        AgentRequest("u1", "旅行を計画"),
    )

    assert result.text == "handled by travel"


def test_router_rejects_explicit_disabled_agent():
    registry = AgentRegistry(
        [FakeAgent("travel", "Travel", "旅行", enabled=False)]
    )

    with pytest.raises(ValueError, match="agent is disabled"):
        AgentRouter(registry).route_to(
            "travel",
            AgentRequest("u1", "旅行を計画"),
        )


def test_registry_priority_wins_when_multiple_agents_match():
    registry = AgentRegistry(
        [
            FakeAgent("generic", "Generic", "天気", priority=1),
            FakeAgent("specialized", "Specialized", "天気", priority=10),
        ]
    )

    result = AgentRouter(registry).route(AgentRequest("u1", "天気"))

    assert result.agent == "specialized"


def test_disabled_agent_is_not_selected():
    registry = AgentRegistry(
        [FakeAgent("weather", "Weather", "天気", enabled=False)]
    )

    assert AgentRouter(registry).route(AgentRequest("u1", "天気")).agent is None


def test_router_accepts_string_agent_response():
    registry = AgentRegistry(
        [FakeAgent("news", "News", "ニュース", return_text=True)]
    )

    result = AgentRouter(registry).route(AgentRequest("u1", "ニュース"))

    assert result.response == AgentResponse(text="handled by news")


def test_router_rejects_invalid_agent_response():
    @dataclass
    class BadAgent(FakeAgent):
        def handle(self, request: AgentRequest):
            return object()

    registry = AgentRegistry([BadAgent("bad", "Bad", "bad")])

    with pytest.raises(TypeError, match="AgentResponse or str"):
        AgentRouter(registry).route(AgentRequest("u1", "bad"))


def test_router_rejects_wrong_registry_type():
    with pytest.raises(TypeError, match="registry must be an AgentRegistry"):
        AgentRouter(object())


def test_registry_rejects_agent_without_can_handle():
    class IncompleteAgent:
        name = "broken"
        description = "Broken"
        handle = lambda self, request: AgentResponse(text="x")

    with pytest.raises(TypeError, match="can_handle"):
        AgentRegistry([IncompleteAgent()])
