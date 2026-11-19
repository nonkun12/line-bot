"""Small seam for incrementally moving legacy graph agents to Core."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from core.agents import AgentRegistry
from graph.core_graph import build_current_core_graph


def should_route_to_core(
    state: Mapping[str, Any],
    migrated_agents: Iterable[str],
) -> bool:
    """Return whether the selected agent is explicitly migrated to Core."""
    next_agent = state.get("next_agent")
    if not isinstance(next_agent, str):
        return False
    return next_agent in set(migrated_agents)


def run_migrated_agent(
    state: Mapping[str, Any],
    registry: AgentRegistry,
    *,
    migrated_agents: Iterable[str],
) -> dict[str, Any]:
    """Execute the Core graph only for an explicitly migrated agent.

    The returned state keeps all caller fields while applying the Core graph's
    route/result/final reply updates. Callers can therefore insert this seam
    before replacing an individual legacy LangGraph node.
    """
    if not should_route_to_core(state, migrated_agents):
        raise ValueError("agent is not enabled for Core migration")

    result = build_current_core_graph(registry=registry).invoke(dict(state))
    return {**dict(state), **dict(result)}
