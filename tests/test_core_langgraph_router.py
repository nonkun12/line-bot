from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.langgraph_router import route_with_core


class WeatherAgent:
    name = "weather"
    description = "weather"
    priority = 10
    enabled = True
    graph_node = "weather_agent"

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("next_agent") == "weather"

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="ok")


def test_core_agent_route_wins_when_registered():
    registry = AgentRegistry([WeatherAgent()])

    assert route_with_core(
        {
            "user_id": "u1",
            "raw_message": "天気",
            "next_agent": "weather",
        },
        registry,
    ) == "weather_agent"


def test_core_agent_can_provide_custom_graph_node():
    class CustomAgent(WeatherAgent):
        name = "calendar"
        graph_node = "calendar_agent"

        def can_handle(self, request: AgentRequest) -> bool:
            return request.metadata.get("next_agent") == "calendar"

    registry = AgentRegistry([CustomAgent()])

    assert route_with_core(
        {"user_id": "u1", "raw_message": "予定", "next_agent": "calendar"},
        registry,
    ) == "calendar_agent"


def test_disabled_core_agent_does_not_fall_through_to_legacy_route():
    agent = WeatherAgent()
    agent.enabled = False
    registry = AgentRegistry([agent])

    assert route_with_core(
        {
            "user_id": "u1",
            "raw_message": "天気",
            "next_agent": "weather",
        },
        registry,
    ) == "fallback_agent"


def test_legacy_route_is_used_when_core_has_no_match():
    registry = AgentRegistry()

    assert route_with_core(
        {"user_id": "u1", "raw_message": "メモ", "next_agent": "notes"},
        registry,
    ) == "notes_agent"


def test_unknown_route_uses_fallback():
    registry = AgentRegistry()

    assert route_with_core(
        {"user_id": "u1", "raw_message": "?", "next_agent": "unknown"},
        registry,
    ) == "fallback_agent"
