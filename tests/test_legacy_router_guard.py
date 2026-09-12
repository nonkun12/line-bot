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


def test_feature_agents_have_expected_registry_names_and_graph_nodes() -> None:
    expected_legacy_nodes = {
        "english_learning": "english_learning_agent",
        "stocks": "stocks_agent",
        "ai_news": "ai_news_agent",
        "voice": "voice_agent",
    }

    assert {
        name: LEGACY_GRAPH_NODES[name] for name in expected_legacy_nodes
    } == expected_legacy_nodes

    registry = build_core_agent_registry()
    expected_registry_names = {
        "english_learning": "english_learning",
        "stocks": "stocks",
        "ai_news": "ai_news",
        "voice": "voice",
    }
    assert {
        name: registry.get(name).name for name in expected_registry_names
    } == expected_registry_names

    # The legacy English-learning adapter still exposes graph_node. Migrated
    # feature agents are native Agent implementations and intentionally do not
    # need that legacy field.
    assert registry.get("english_learning").graph_node == expected_legacy_nodes[
        "english_learning"
    ]
