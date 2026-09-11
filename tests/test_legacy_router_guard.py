import pytest

from graph.core_registry import build_core_agent_registry
from graph.router import route_from_supervisor


@pytest.mark.parametrize("next_agent", ["stocks", "ai_news", "voice"])
def test_legacy_router_does_not_return_nonexistent_future_agent_node(next_agent: str) -> None:
    registry = build_core_agent_registry()
    state = {
        "user_id": "test-user",
        "raw_message": "test",
        "channel": "line",
        "metadata": {},
        "next_agent": next_agent,
    }

    assert route_from_supervisor(state, registry) == "fallback_agent"


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
