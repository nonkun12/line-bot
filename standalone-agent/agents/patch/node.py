"""
Phase4a: Patch Apply Node

AUTO_APPLY_PATCH=false (デフォルト) の場合は何もせず、
Fix Agentまでの結果をそのまま次のノードへ流す。
"""

import os

from graph.state import AgentState
from agents.patch.apply import apply_patch
from agents.patch.generator import generate_patch_candidates


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


def patch_generate_node(state: AgentState) -> AgentState:
    """
    Phase3: Patch候補生成ノード

    Fix Agentの結果(agent_results["fix"])からPatch候補
    (PatchCandidateのリスト)を生成し、stateに格納する。

    重要:
    - このノードはファイルの読み書き・git操作を一切行わない。
    - 実際のファイル変更は既存の patch_apply_node (Phase4a) が
      AUTO_APPLY_PATCH=true の場合にのみ行う。このノードは
      その適用可否を決定・実行しない(候補生成のみ)。
    """

    results = dict(
        state.get("agent_results", {})
    )

    fix_result = results.get("fix", {}) or {}

    try:
        candidates = generate_patch_candidates(fix_result)
        error = None

    except Exception as e:
        candidates = []
        error = str(e)

    patch_candidates_result = {
        "candidates": candidates,
        "count": len(candidates),
    }

    if error:
        patch_candidates_result["error"] = error

    results["patch_candidates"] = patch_candidates_result

    return {
        **state,
        "agent_results": results,
        "patch_candidates": candidates,
    }
