"""AI Secretary work-status Agent."""

from graph.state import AgentState


def work_status_agent_node(state: AgentState) -> AgentState:
    """Generate the existing AI secretary work-status report."""
    user_id = state.get("user_id", "")

    try:
        # Reuse the already-tested report implementation in app.py instead of
        # duplicating GitHub/memory/reminder collection logic.
        from app import generate_ai_secretary_report

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
