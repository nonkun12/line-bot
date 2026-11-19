from dataclasses import dataclass

from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.langgraph_router import route_with_core
from core.langgraph_adapter import agent_request_from_state
from graph.router import route_from_supervisor


@dataclass(frozen=True)
class FakeAgent:
    name: str
    description: str = "test"
    priority: int = 100
    enabled: bool = True
    graph_node: str = ""

    def can_handle(self, request: AgentRequest) -> bool:
        return request.message == "英語を勉強したい"

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="ok")


def test_core_route_prefers_explicit_registered_agent():
    registry = AgentRegistry([FakeAgent("english", graph_node="english_agent")])
    state = {"user_id": "u1", "raw_message": "英語を勉強したい", "next_agent": "english"}
    assert route_with_core(state, registry) == "english_agent"


def test_core_route_can_resolve_new_agent_without_legacy_route():
    registry = AgentRegistry([FakeAgent("english", graph_node="english_agent")])
    state = {"user_id": "u1", "raw_message": "英語を勉強したい", "next_agent": "unknown"}
    assert route_with_core(state, registry) == "english_agent"


def test_disabled_core_agent_falls_back_safely():
    registry = AgentRegistry([FakeAgent("english", enabled=False, graph_node="english_agent")])
    state = {"user_id": "u1", "raw_message": "英語を勉強したい", "next_agent": "english"}
    assert route_with_core(state, registry) == "fallback_agent"


def test_legacy_route_is_unchanged_without_registry():
    assert route_from_supervisor({"next_agent": "weather"}) == "weather_agent"
    assert route_from_supervisor({"next_agent": "does_not_exist"}) == "fallback_agent"


def test_equal_priority_resolution_is_deterministic():
    registry = AgentRegistry(
        [
            FakeAgent("zeta", graph_node="zeta_agent"),
            FakeAgent("alpha", graph_node="alpha_agent"),
        ]
    )
    request = AgentRequest(user_id="u1", message="英語を勉強したい")
    assert registry.resolve(request).name == "alpha"


def test_adapter_preserves_shared_metadata():
    marker = object()
    state = {
        "user_id": "u1",
        "raw_message": "英語を勉強したい",
        "request_id": "r1",
        "intent": "english",
        "next_agent": "english",
        "metadata": {"channel": "voice", "marker": marker},
    }
    request = agent_request_from_state(state)
    assert request.metadata["channel"] == "voice"
    assert request.metadata["marker"] is marker
    assert request.metadata["next_agent"] == "english"
