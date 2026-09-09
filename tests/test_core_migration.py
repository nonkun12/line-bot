import pytest

from core.legacy_adapter import LegacyNodeAgent
from core.agents import AgentRegistry
from graph.core_migration import run_migrated_agent, should_route_to_core


def test_should_route_to_core_only_for_selected_agent():
    assert should_route_to_core({"next_agent": "notes"}, {"notes"}) is True
    assert should_route_to_core({"next_agent": "weather"}, {"notes"}) is False
    assert should_route_to_core({"next_agent": None}, {"notes"}) is False


def test_run_migrated_agent_executes_core_graph_for_selected_agent():
    def fake_notes_node(state):
        return {
            **state,
            "agent_results": {
                "notes": {"text": "core notes result"},
            },
        }

    registry = AgentRegistry(
        [
            LegacyNodeAgent(
                name="notes",
                node=fake_notes_node,
                graph_node="notes_agent",
            )
        ]
    )

    result = run_migrated_agent(
        {
            "user_id": "u1",
            "raw_message": "メモして",
            "next_agent": "notes",
            "agent_results": {},
        },
        registry,
        migrated_agents={"notes"},
    )

    assert result["agent_results"]["notes"]["text"] == "core notes result"
    assert result["final_reply"] == "core notes result"


def test_run_migrated_agent_rejects_non_migrated_agent():
    registry = AgentRegistry([])

    with pytest.raises(ValueError, match="not enabled for Core migration"):
        run_migrated_agent(
            {"next_agent": "weather"},
            registry,
            migrated_agents={"notes"},
        )
