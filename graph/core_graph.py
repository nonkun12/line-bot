"""Core-native graph factory for the currently migrated agents."""

from __future__ import annotations

from core.langgraph_runtime import build_core_graph
from graph.core_registry import build_core_agent_registry


def build_current_core_graph():
    """Build a LangGraph using the shared Core registry and migrated agents."""
    return build_core_graph(build_core_agent_registry())
