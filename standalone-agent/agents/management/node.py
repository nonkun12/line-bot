"""Management AI: classify development work and assign a specialist."""

from __future__ import annotations

from graph.state import AgentState

REFACTOR_KEYWORDS = (
    "refactor", "refactoring", "リファクタ", "リファクタリング",
    "整理", "重複削減", "可読性", "簡素化", "complexity", "cleanup",
)


def assign_agent(message: str) -> str:
    text = (message or "").strip().lower()
    if any(keyword in text for keyword in REFACTOR_KEYWORDS):
        return "refactoring_agent"
    return "development_agent"


def management_agent_node(state: AgentState) -> AgentState:
    message = state.get("raw_message", "") or ""
    assigned = assign_agent(message)
    plan = {
        "assigned_agent": assigned,
        "reason": "refactoring intent detected" if assigned == "refactoring_agent" else "development task",
    }
    results = dict(state.get("agent_results", {}))
    results["management"] = {"assigned_agent": assigned, "summary": f"assigned to {assigned}"}
    return {
        **state,
        "next_agent": assigned,
        "management_plan": plan,
        "agent_results": results,
    }
