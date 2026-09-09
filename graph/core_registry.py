"""Build the Core registry from the existing LangGraph agent nodes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agents.github.node import github_agent_node
from agents.memory.node import memory_agent_node
from agents.notes.node import notes_agent_node
from agents.normal.node import normal_agent_node
from agents.sheets.node import sheets_agent_node
from agents.weather.node import weather_agent_node
from core.legacy_adapter import build_legacy_registry


LEGACY_AGENT_NODES: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
    "github": github_agent_node,
    "memory": memory_agent_node,
    "notes": notes_agent_node,
    "normal": normal_agent_node,
    "sheets": sheets_agent_node,
    "weather": weather_agent_node,
}

LEGACY_GRAPH_NODES: Mapping[str, str] = {
    "github": "github_agent",
    "memory": "memory_agent",
    "notes": "notes_agent",
    "normal": "normal_agent",
    "sheets": "sheets_agent",
    "weather": "weather_agent",
}


def build_core_agent_registry():
    """Return a registry containing the currently migrated legacy agents."""
    return build_legacy_registry(
        LEGACY_AGENT_NODES,
        graph_nodes=LEGACY_GRAPH_NODES,
    )
