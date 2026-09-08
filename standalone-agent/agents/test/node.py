"""
Phase4a: Test Runner Node

patch_apply_nodeでpatchが実際に適用された場合のみpytestを実行する。
patch適用がスキップ(AUTO_APPLY_PATCH=false)または失敗した場合は、
テストを実行せずそのまま通過する。
"""

import os

from graph.state import AgentState
from agents.test.runner import run_tests


def test_runner_node(state: AgentState) -> AgentState:

    patch_result = state.get("patch_result", {}) or {}

    results = dict(
        state.get("agent_results", {})
    )

    if patch_result.get("skipped") or not patch_result.get("applied"):
        test_result = {
            "skipped": True,
            "passed": None,
            "reason": "patch not applied",
        }

        results["test"] = test_result

        return {
            **state,
            "agent_results": results,
            "test_result": test_result,
        }

    workdir = os.environ.get(
        "REPO_WORKDIR",
        os.getcwd()
    )

    test_result = run_tests(cwd=workdir)
    test_result["skipped"] = False

    results["test"] = test_result

    return {
        **state,
        "agent_results": results,
        "test_result": test_result,
    }
