from core.langgraph_runtime import agent_node_name
from graph.core_graph import build_current_core_graph
import agents.memory.node as memory_node


def test_current_core_graph_executes_memory_agent_through_registry(monkeypatch):
    monkeypatch.setattr(
        memory_node,
        "handle_memory_message",
        lambda message, user_id, call_mcp_tool: "記憶しました。",
    )

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "これを覚えて",
            "next_agent": "memory",
            "agent_results": {},
        }
    )

    assert result["route"] == agent_node_name("memory")
    assert result["final_reply"] == "記憶しました。"
    assert result["agent_results"]["memory"]["text"] == "記憶しました。"
