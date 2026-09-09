import pytest

from agents.notes.node import notes_agent_node
from core.agents import AgentRequest
from core.legacy_adapter import LegacyNodeAgent, build_legacy_registry


def legacy_node(state):
    return {
        **state,
        "agent_results": {
            "demo": {"text": "legacy ok", "success": True}
        },
    }


def test_legacy_node_agent_adapts_state_node():
    agent = LegacyNodeAgent(
        name="demo",
        node=legacy_node,
        graph_node="demo_agent",
    )

    request = AgentRequest(
        user_id="u1",
        message="hello",
        metadata={"next_agent": "demo", "request_id": "r1"},
    )

    assert agent.can_handle(request) is True
    response = agent.handle(request)
    assert response.text == "legacy ok"
    assert response.metadata["success"] is True


def test_legacy_node_agent_prefers_final_reply_when_agent_result_is_missing():
    agent = LegacyNodeAgent(
        name="demo",
        node=lambda state: {**state, "final_reply": "fallback reply"},
    )

    response = agent.handle(AgentRequest(user_id="u1", message="hello"))
    assert response.text == "fallback reply"


def test_legacy_node_agent_rejects_non_mapping_node_result():
    agent = LegacyNodeAgent(name="demo", node=lambda state: "bad")

    with pytest.raises(TypeError, match="legacy node must return a mapping"):
        agent.handle(AgentRequest(user_id="u1", message="hello"))


def test_build_legacy_registry_preserves_graph_node_and_route_key():
    registry = build_legacy_registry(
        {"demo": legacy_node},
        graph_nodes={"demo": "demo_agent"},
        priorities={"demo": 10},
    )

    agent = registry.get("demo")
    assert agent.graph_node == "demo_agent"
    assert agent.priority == 10
    assert registry.resolve(
        AgentRequest(user_id="u1", message="hello", metadata={"next_agent": "demo"})
    ) is agent


def test_legacy_node_agent_wraps_real_notes_node():
    calls = []

    def fake_call_mcp_tool(tool_name, arguments, timeout=3.0):
        calls.append((tool_name, arguments))
        assert tool_name == "save_note"
        return "メモ「テスト」を保存しました。"

    agent = LegacyNodeAgent(
        name="notes",
        node=notes_agent_node,
        graph_node="notes_agent",
    )

    response = agent.handle(
        AgentRequest(
            user_id="u1",
            message="メモにテストを保存して",
            metadata={"next_agent": "notes", "call_mcp_tool": fake_call_mcp_tool},
        )
    )

    assert response.text == "メモ「テスト」を保存しました。"
    assert calls == [
        (
            "save_note",
            {
                "user_id": "u1",
                "title": "LINEメモ",
                "body": "テスト",
                "category": "一般",
            },
        )
    ]
