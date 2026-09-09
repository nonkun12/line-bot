from graph.core_graph import build_current_core_graph
from core.langgraph_runtime import agent_node_name


def test_current_core_graph_compiles_with_migrated_agents():
    graph = build_current_core_graph()
    graph_nodes = set(graph.get_graph().nodes)

    assert agent_node_name("weather") in graph_nodes
    assert agent_node_name("notes") in graph_nodes
    assert agent_node_name("github") in graph_nodes
    assert "core_router" in graph_nodes
    assert "core_finalizer" in graph_nodes


def test_current_core_graph_routes_explicit_agent():
    graph = build_current_core_graph()

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "test",
            "next_agent": "normal",
            "agent_results": {},
        }
    )

    assert result["next_agent"] == "normal"
    assert "normal" in result["agent_results"]
