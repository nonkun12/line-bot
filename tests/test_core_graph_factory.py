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
