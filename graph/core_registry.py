"""Build the Core registry from the existing and newly migrated agent nodes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agents.app_development.node import app_development_agent_node
from agents.debug.node import debug_agent_node
from agents.github.node import github_agent_node
from agents.memory.node import memory_agent_node
from agents.notes.node import notes_agent_node
from agents.normal.node import normal_agent_node
from agents.sheets.node import sheets_agent_node
from agents.weather.node import weather_agent_node
from agents.english.node import english_learning_agent_node
from agents.stocks.node import agent as stocks_agent
from agents.news.node import agent as ai_news_agent
from agents.voice.node import agent as voice_agent
from core.legacy_adapter import build_legacy_registry
from core.agents import AgentRegistry

LEGACY_AGENT_NODES: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
    "app_development": app_development_agent_node,
    "debug": debug_agent_node,
    "github": github_agent_node,
    "memory": memory_agent_node,
    "notes": notes_agent_node,
    "normal": normal_agent_node,
    "sheets": sheets_agent_node,
    "weather": weather_agent_node,
    "english_learning": english_learning_agent_node,
}

LEGACY_GRAPH_NODES: Mapping[str, str] = {
    "debug": "debug_agent",
    "app_development": "app_development_agent",
    "notes": "notes_agent",
    "memory": "memory_agent",
    "github": "github_agent",
    "sheets": "sheets_agent",
    "weather": "weather_agent",
    "normal": "normal_agent",
    "english_learning": "english_learning_agent",
    "stocks": "stocks_agent",
    "ai_news": "ai_news_agent",
    "voice": "voice_agent",
    "fallback": "fallback_agent",
}


def build_core_agent_registry() -> AgentRegistry:
    """Return the shared Core registry, including the future feature agents."""
    registry = build_legacy_registry(
        LEGACY_AGENT_NODES,
        graph_nodes=LEGACY_GRAPH_NODES,
        priorities={"app_development": 100, "debug": 90},
    )
    registry.register(stocks_agent)
    registry.register(ai_news_agent)
    registry.register(voice_agent)
    return registry
