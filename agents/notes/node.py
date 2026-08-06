from typing import Any

import mcp_client
from graph.state import AgentState
from agents.notes.handlers import (
    handle_note_message,
)


def _call_mcp_tool(state: AgentState):
    call_mcp_tool = state.get("call_mcp_tool")
    if callable(call_mcp_tool):
        return call_mcp_tool
    return mcp_client.call_mcp_tool


def notes_agent_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = _call_mcp_tool(state)

    result_text = handle_note_message(raw_message, user_id, call_mcp_tool)

    if result_text is None:
        result_text = "Notes Botはこのリクエストに対応していません。"

    agent_results = dict(state.get("agent_results", {}))
    agent_results["notes"] = {
        "text": result_text,
    }

    return {
        **state,
        "agent_results": agent_results,
    }
