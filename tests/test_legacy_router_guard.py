import pytest

from graph.core_registry import LEGACY_GRAPH_NODES, build_core_agent_registry
from graph.router import route_from_supervisor


@pytest.mark.parametrize(
    ("next_agent", "expected_node"),
    [
        ("stocks", "stocks_agent"),
        ("ai_news", "ai_news_agent"),
        ("voice", "voice_agent"),
    ],
)
def test_router_returns_registered_feature_agent_nodes(
    next_agent: str, expected_node: str
) -> None:
    registry = build_core_agent_registry()
    state = {
        "user_id": "test-user",
        "raw_message": "test",
        "channel": "line",
        "metadata": {},
        "next_agent": next_agent,
    }

    assert route_from_supervisor(state, registry) == expected_node


def test_legacy_router_keeps_existing_english_learning_node() -> None:
    registry = build_core_agent_registry()
    state = {
        "user_id": "test-user",
        "raw_message": "test",
        "channel": "line",
        "metadata": {},
        "next_agent": "english_learning",
    }

    assert route_from_supervisor(state, registry) == "english_learning_agent"


def test_feature_agents_have_graph_node_registrations() -> None:
    expected = {
        "english_learning": "english_learning_agent",
        "stocks": "stocks_agent",
        "ai_news": "ai_news_agent",
        "voice": "voice_agent",
    }

    assert {name: LEGACY_GRAPH_NODES[name] for name in expected} == expected
    registry = build_core_agent_registry()
    for name, node in expected.items():
        assert registry.get(name).graph_node == node
