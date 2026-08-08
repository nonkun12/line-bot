"""
Normal Agent LangGraph Node

GitHub / Debug / Memory / Notes のいずれの意図にも該当しない
通常メッセージに対して、Groq(function calling)ベースの
AI応答を生成するノード。
"""

import mcp_client
from graph.state import AgentState
from agents.normal.handlers import handle_normal_message


def _call_mcp_tool(state: AgentState):
    call_mcp_tool = state.get("call_mcp_tool")
    if callable(call_mcp_tool):
        return call_mcp_tool
    return mcp_client.call_mcp_tool


def normal_agent_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = _call_mcp_tool(state)

    result_text = handle_normal_message(raw_message, user_id, call_mcp_tool)

    agent_results = dict(state.get("agent_results", {}))
    agent_results["normal"] = {
        "text": result_text,
    }

    return {
        **state,
        "agent_results": agent_results,
    }
