"""Registry-first routing bridge for incremental LangGraph migration.

The Core registry is consulted first. When no Core agent matches, callers can
fall back to the legacy LangGraph route table. The bridge intentionally does
not replace existing routing by itself.
"""

from __future__ import annotations

from typing import Mapping, Any

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
    """Resolve a registered Core agent before using the legacy route table."""
    if not isinstance(registry, AgentRegistry):
        raise TypeError("registry must be an AgentRegistry")

    request = agent_request_from_state(state)
    agent = registry.resolve(request)
    if agent is not None:
        graph_node = getattr(agent, "graph_node", None)
        return graph_node if isinstance(graph_node, str) and graph_node.strip() else f"{agent.name}_agent"

    next_agent = state.get("next_agent")
    return legacy_routes.get(next_agent, default_route)
