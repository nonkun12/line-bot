"""Core-native graph factory for the currently migrated agents."""

from __future__ import annotations

from core.agents import AgentRegistry
from core.langgraph_runtime import build_core_graph
from graph.core_registry import build_core_agent_registry


def build_current_core_graph(
    *,
    registry: AgentRegistry | None = None,
):
    """Build a LangGraph using the supplied or shared Core registry."""
    return build_core_graph(registry or build_core_agent_registry())
