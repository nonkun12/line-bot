"""
Memory Agent LangGraph Node
"""


from .handlers import handle_memory_message


def memory_agent_node(state):
    """
    LangGraph Memory Agent Node
    """

    result = handle_memory_message(
        state["raw_message"],
        state["user_id"],
        state.get("call_mcp_tool")
    )

    state.setdefault(
        "agent_results",
        {}
    )

    state["agent_results"]["memory"] = result

    return state