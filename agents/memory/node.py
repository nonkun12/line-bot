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

    agent_results = dict(state.get("agent_results", {}))

    if result is not None:
        agent_results["memory"] = {
            "text": result,
        }

    return {
        **state,
        "agent_results": agent_results,
    }