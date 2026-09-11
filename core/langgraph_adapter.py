"""Thin adapter from legacy LangGraph state into the channel-independent Core.

This module intentionally does not change the existing graph routing behavior.
It only provides a safe translation boundary for a later incremental migration.
"""

from __future__ import annotations

from typing import Any, Mapping

from .agents import AgentRequest, AgentResponse
from .gateway import AIRequest


def _build_metadata(state: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve shared metadata while refreshing canonical routing fields."""
    metadata = dict(state.get("metadata", {}) or {})
    metadata.update(
        {
            "request_id": state.get("request_id"),
            "intent": state.get("intent"),
            "next_agent": state.get("next_agent"),
        }
    )
    if callable(state.get("call_mcp_tool")):
        metadata["call_mcp_tool"] = state["call_mcp_tool"]
    return metadata


def ai_request_from_state(state: Mapping[str, Any], *, channel: str = "line") -> AIRequest:
    """Translate legacy AgentState-like data into an AIRequest."""
    return AIRequest(
        user_id=state.get("user_id", ""),
        message=state.get("raw_message", ""),
        channel=channel,
        metadata=_build_metadata(state),
    )


def agent_request_from_state(state: Mapping[str, Any]) -> AgentRequest:
    """Translate legacy AgentState-like data into an AgentRequest."""
    return AgentRequest(
        user_id=state.get("user_id", ""),
        message=state.get("raw_message", ""),
        metadata=_build_metadata(state),
    )


def response_text(response: AgentResponse | str) -> str:
    """Normalize a Core response for legacy graph consumers."""
    if isinstance(response, AgentResponse):
        return response.text
    if isinstance(response, str):
        return response
    raise TypeError("response must be AgentResponse or str")
