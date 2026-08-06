from graph.state import AgentState
from .handlers import handle_github_message


def github_agent_node(state: AgentState) -> AgentState:
    """
    LangGraph GitHub Agent Node
    """

    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = state.get("call_mcp_tool")

    result_text = handle_github_message(
        raw_message,
        user_id,
        call_mcp_tool,
    )

    agent_results = dict(state.get("agent_results", {}))
    agent_results["github"] = {
        "text": result_text,
    }

    return {
        **state,
        "agent_results": agent_results,
    }
