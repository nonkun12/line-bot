from core.agents import AgentRequest
from graph.core_registry import LEGACY_AGENT_NODES, LEGACY_GRAPH_NODES, build_core_agent_registry


def test_core_registry_contains_all_migrated_legacy_agents():
    registry = build_core_agent_registry()

    assert set(registry.names()) == set(LEGACY_AGENT_NODES)
    for name, graph_node in LEGACY_GRAPH_NODES.items():
        agent = registry.get(name)
        assert agent.graph_node == graph_node
        assert agent.route_key == name


def test_core_registry_resolves_explicit_legacy_route():
    registry = build_core_agent_registry()

    agent = registry.resolve(
        AgentRequest(
            user_id="u1",
            message="天気",
            metadata={"next_agent": "weather"},
        )
    )

    assert agent is registry.get("weather")
    assert agent.graph_node == "weather_agent"
