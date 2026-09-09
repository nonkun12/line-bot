"""Registry-first routing bridge for incremental LangGraph migration.

The Core registry is consulted first. When no Core agent matches, callers can
fall back to the legacy LangGraph route table. The bridge intentionally does
not replace existing routing by itself.
"""

from __future__ import annotations

from typing import Any, Mapping

from .agents import AgentRegistry
from .langgraph_adapter import agent_request_from_state


LEGACY_GRAPH_NODES: Mapping[str, str] = {
    "debug": "debug_agent",
    "notes": "notes_agent",
    "memory": "memory_agent",
    "github": "github_agent",
    "sheets": "sheets_agent",
    "weather": "weather_agent",
    "normal": "normal_agent",
    "fallback": "fallback_agent",
}


def route_with_core(
    state: Mapping[str, Any],
    registry: AgentRegistry,
    *,
    legacy_routes: Mapping[str, str] = LEGACY_GRAPH_NODES,
    default_route: str = "fallback_agent",
) -> str:
    """Resolve an explicitly selected Core agent before generic matching."""
    if not isinstance(registry, AgentRegistry):
        raise TypeError("registry must be an AgentRegistry")

    request = agent_request_from_state(state)
    next_agent = state.get("next_agent")

    # Supervisor-selected agents must take precedence over broad can_handle
    # predicates. A future agent may inherit shared behavior while still
    # honoring the explicit route selected by the legacy graph.
    if isinstance(next_agent, str) and next_agent.strip():
        try:
            selected = registry.get(next_agent)
        except KeyError:
            selected = None
        if selected is not None and bool(getattr(selected, "enabled", True)):
            graph_node = getattr(selected, "graph_node", None)
            if isinstance(graph_node, str) and graph_node.strip():
                return graph_node
            return f"{selected.name}_agent"

    agent = registry.resolve(request)
    if agent is not None:
        graph_node = getattr(agent, "graph_node", None)
        return graph_node if isinstance(graph_node, str) and graph_node.strip() else f"{agent.name}_agent"

    return legacy_routes.get(next_agent, default_route)
