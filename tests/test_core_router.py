from dataclasses import dataclass

import pytest

from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.router import AgentRouter, RouteResult


@dataclass
class FakeAgent:
    name: str
    description: str
    keyword: str

    def can_handle(self, request: AgentRequest) -> bool:
        return self.keyword in request.message

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text=f"handled by {self.name}")


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


def test_router_rejects_wrong_registry_type():
    with pytest.raises(TypeError, match="registry must be an AgentRegistry"):
        AgentRouter(object())
