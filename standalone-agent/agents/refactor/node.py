"""Refactor specialist for behavior-preserving maintenance work."""

from __future__ import annotations

from agents.development.node import development_agent_node
from graph.state import AgentState


def refactor_agent_node(state: AgentState) -> AgentState:
    """Run the existing safe patch pipeline under a refactor-specific role.

    The management layer decides when this specialist is appropriate. The
    specialist reuses the established protected-path and git-apply safeguards;
    its dedicated prompt policy is represented in the role metadata so review
    and audit layers can distinguish maintenance work from feature work.
    """
    results = dict(state.get("agent_results", {}))
    results["refactor"] = {
        "role": "refactor",
        "policy": "preserve behavior; no new features; minimal diff",
    }
    updated = {**state, "agent_results": results}
    result = development_agent_node(updated)
    results = dict(result.get("agent_results", {}))
    results["refactor"] = {
        **results.get("refactor", {}),
        "applied": bool(result.get("patch_result", {}).get("applied")),
        "summary": "behavior-preserving maintenance patch applied" if result.get("patch_result", {}).get("applied") else "refactor patch was not applied",
    }
    return {**result, "agent_results": results}
