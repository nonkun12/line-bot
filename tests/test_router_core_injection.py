from core.agents import AgentRegistry, AgentRequest, AgentResponse
from graph.router import route_from_supervisor


class CalendarAgent:
    name = "calendar"
    description = "calendar"
    priority = 10
    enabled = True
    graph_node = "calendar_agent"

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("next_agent") == "calendar"

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="予定")


def test_router_preserves_legacy_behavior_without_registry():
    assert route_from_supervisor({"next_agent": "weather"}) == "weather_agent"
    assert route_from_supervisor({"next_agent": "unknown"}) == "fallback_agent"


def test_router_uses_core_registry_when_injected():
    registry = AgentRegistry([CalendarAgent()])

    assert route_from_supervisor(
        {
            "user_id": "u1",
            "raw_message": "明日の予定",
            "next_agent": "calendar",
        },
        registry,
    ) == "calendar_agent"


def test_router_uses_legacy_fallback_for_unregistered_agent():
    registry = AgentRegistry([CalendarAgent()])

    assert route_from_supervisor(
        {"user_id": "u1", "raw_message": "天気", "next_agent": "weather"},
        registry,
    ) == "weather_agent"
