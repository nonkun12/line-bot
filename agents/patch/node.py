"""
Phase4a: Patch Apply Node

AUTO_APPLY_PATCH=false (デフォルト) の場合は何もせず、
Fix Agentまでの結果をそのまま次のノードへ流す。
"""

import os

from graph.state import AgentState
from agents.patch.apply import apply_patch


def _auto_apply_enabled() -> bool:
    return os.environ.get(
        "AUTO_APPLY_PATCH",
        "false"
    ).lower() == "true"


def patch_apply_node(state: AgentState) -> AgentState:

    results = dict(
        state.get("agent_results", {})
    )

    if not _auto_apply_enabled():
        patch_result = {
            "skipped": True,
            "applied": False,
            "reason": "AUTO_APPLY_PATCH is disabled",
        }

        results["patch"] = patch_result

        return {
            **state,
            "agent_results": results,
            "patch_result": patch_result,
        }

    fix_result = results.get("fix", {}) or {}

    patch_text = fix_result.get("patch", "")

    workdir = os.environ.get(
        "REPO_WORKDIR",
        os.getcwd()
    )

    patch_result = apply_patch(patch_text, workdir)
    patch_result["skipped"] = False

    results["patch"] = patch_result

    return {
        **state,
        "agent_results": results,
        "patch_result": patch_result,
    }
