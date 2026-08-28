"""AI Secretary work-status Agent."""

from graph.state import AgentState
from ai_secretary_report import generate_ai_secretary_report


def work_status_agent_node(state: AgentState) -> AgentState:
    """Generate the existing AI secretary work-status report."""
    user_id = state.get("user_id", "")

    try:
        result_text = generate_ai_secretary_report(user_id)
    except Exception as exc:
        print("[WORK STATUS] AI secretary report error:", exc)
        result_text = "作業確認の取得中にエラーが発生しました。もう一度お試しください。"

    agent_results = dict(state.get("agent_results", {}))
    agent_results["work_status"] = {
        "text": result_text,
    }

    return {
        **state,
        "agent_results": agent_results,
    }
