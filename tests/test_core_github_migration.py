from core.langgraph_runtime import agent_node_name
from graph.core_graph import build_current_core_graph
import agents.github.node as github_node


def test_current_core_graph_executes_github_agent_through_registry(monkeypatch):
    monkeypatch.setattr(
        github_node,
        "handle_github_message",
        lambda message, user_id, call_mcp_tool: "GitHub情報を取得しました。",
    )

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "github repoを教えて",
            "next_agent": "github",
            "agent_results": {},
        }
    )

    assert result["route"] == agent_node_name("github")
    assert result["final_reply"] == "GitHub情報を取得しました。"
    assert result["agent_results"]["github"]["text"] == "GitHub情報を取得しました。"
