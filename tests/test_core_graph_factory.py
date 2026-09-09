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


def test_current_core_graph_contains_route_edges_for_migrated_agents():
    graph = build_current_core_graph()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    assert ("core_router", agent_node_name("weather")) in edges
    assert (agent_node_name("weather"), "core_finalizer") in edges
    assert ("core_fallback", "core_finalizer") in edges
