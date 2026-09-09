import pytest

from core.legacy_adapter import LegacyNodeAgent
from core.agents import AgentRegistry
from graph.core_migration import run_migrated_agent, should_route_to_core


def test_should_route_to_core_only_for_selected_agent():
    assert should_route_to_core({"next_agent": "notes"}, {"notes"}) is True
    assert should_route_to_core({"next_agent": "weather"}, {"notes"}) is False
    assert should_route_to_core({"next_agent": None}, {"notes"}) is False


def test_should_route_to_core_rejects_blank_or_untrimmed_selection():
    assert should_route_to_core({"next_agent": ""}, {"notes"}) is False
    assert should_route_to_core({"next_agent": "  notes  "}, {"notes"}) is False


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


def test_run_migrated_agent_preserves_caller_state():
    def fake_notes_node(state):
        return {
            **state,
            "agent_results": {
                "notes": {"text": "ok"},
            },
        }

    registry = AgentRegistry(
        [LegacyNodeAgent(name="notes", node=fake_notes_node)]
    )
    original = {
        "user_id": "u1",
        "raw_message": "メモして",
        "next_agent": "notes",
        "request_id": "req-1",
        "agent_results": {"existing": {"text": "keep"}},
    }

    result = run_migrated_agent(original, registry, migrated_agents={"notes"})

    assert result["user_id"] == "u1"
    assert result["raw_message"] == "メモして"
    assert result["next_agent"] == "notes"
    assert result["request_id"] == "req-1"
    assert result["final_reply"] == "ok"


def test_run_migrated_agent_rejects_non_migrated_agent():
    registry = AgentRegistry([])

    with pytest.raises(ValueError, match="not enabled for Core migration"):
        run_migrated_agent(
            {"next_agent": "weather"},
            registry,
            migrated_agents={"notes"},
        )


def test_run_migrated_agent_disabled_agent_uses_core_fallback():
    registry = AgentRegistry(
        [
            LegacyNodeAgent(
                name="notes",
                node=lambda state: state,
                enabled=False,
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

    assert result["route"] == "core_fallback"
    assert result["final_reply"] == "対応できるAgentが登録されていません。"
