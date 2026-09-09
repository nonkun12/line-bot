from dataclasses import dataclass

import pytest

from core.agents import AgentRegistry, AgentRequest, AgentResponse


@dataclass
class FakeAgent:
    name: str
    description: str
    keyword: str

    def can_handle(self, request: AgentRequest) -> bool:
        return self.keyword in request.message

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text=f"handled by {self.name}")


def test_registry_supports_arbitrary_agent_types():
    registry = AgentRegistry(
        [
            FakeAgent("english", "English learning", "英語"),
            FakeAgent("news", "News", "ニュース"),
            FakeAgent("stock", "Stocks", "株"),
        ]
    )

    assert registry.names() == ("english", "news", "stock")
    assert registry.resolve(AgentRequest("u1", "株を教えて")).name == "stock"


def test_registry_can_add_future_agent_without_registry_changes():
    registry = AgentRegistry()
    registry.register(FakeAgent("travel", "Travel", "旅行"))

    assert registry.resolve(AgentRequest("u1", "旅行を計画して")).name == "travel"


def test_registry_rejects_duplicate_names():
    agent = FakeAgent("news", "News", "ニュース")
    registry = AgentRegistry([agent])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeAgent("news", "Other", "別"))


def test_registry_rejects_invalid_agent_name():
    with pytest.raises(ValueError, match="agent name is required"):
        AgentRegistry([FakeAgent("", "invalid", "x")])


def test_registry_returns_none_when_no_agent_can_handle_request():
    registry = AgentRegistry([FakeAgent("news", "News", "ニュース")])

    assert registry.resolve(AgentRequest("u1", "こんにちは")) is None


def test_registry_get_unknown_agent_is_explicit():
    registry = AgentRegistry()

    with pytest.raises(KeyError, match="unknown agent"):
        registry.get("future")
