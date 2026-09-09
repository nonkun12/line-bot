from core.langgraph_runtime import agent_node_name
from graph.core_graph import build_current_core_graph


def test_current_core_graph_compiles_with_migrated_agents():
    graph = build_current_core_graph()
    graph_nodes = set(graph.get_graph().nodes)

    assert agent_node_name("weather") in graph_nodes
    assert agent_node_name("notes") in graph_nodes
    assert agent_node_name("github") in graph_nodes
    assert agent_node_name("normal") in graph_nodes
    assert "core_router" in graph_nodes
    assert "core_finalizer" in graph_nodes


def test_current_core_graph_exposes_migrated_nodes_and_terminal_path():
    graph = build_current_core_graph()
    graph_nodes = set(graph.get_graph().nodes)
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    for name in ("weather", "notes", "github", "normal", "memory", "sheets"):
        assert agent_node_name(name) in graph_nodes

    assert ("__start__", "core_router") in edges
    assert ("core_router", "__end__") in edges


def test_current_core_graph_executes_real_notes_agent_through_registry():
    calls = []

    def fake_call_mcp_tool(tool_name, arguments, timeout=3.0):
        calls.append((tool_name, arguments))
        assert tool_name == "save_note"
        return "メモ「テスト」を保存しました。"

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "メモにテストを保存して",
            "next_agent": "notes",
            "call_mcp_tool": fake_call_mcp_tool,
            "agent_results": {},
        }
    )

    assert result["route"] == agent_node_name("notes")
    assert result["final_reply"] == "メモ「テスト」を保存しました。"
    assert result["agent_results"]["notes"]["text"] == "メモ「テスト」を保存しました。"
    assert calls == [
        (
            "save_note",
            {
                "user_id": "u1",
                "title": "LINEメモ",
                "body": "テストを",
                "category": "一般",
            },
        )
    ]
