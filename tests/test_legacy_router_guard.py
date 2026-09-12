import pytest

from graph.core_registry import build_core_agent_registry
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
