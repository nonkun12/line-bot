"""
Phase4c: Deploy Agent

安全設計:
- commit成功後のみ起動
- 初期段階では実deployしない
- 承認待ち状態を返す
"""

import os


def deploy_node(state):

    results = dict(
        state.get("agent_results", {})
    )


    commit_result = state.get(
        "commit_result",
        {}
    )


    if not commit_result.get("committed"):

        deploy_result = {
            "deployed": False,
            "skipped": True,
            "reason": "commit not completed",
        }

        results["deploy"] = deploy_result

        return {
            **state,
            "agent_results": results,
            "deploy_result": deploy_result,
        }


    deploy_result = {
        "deployed": False,
        "pending": True,
        "reason": "waiting for manual approval",
        "commit_hash": commit_result.get(
            "hash"
        ),
    }


    results["deploy"] = deploy_result


    return {
        **state,
        "agent_results": results,
        "deploy_result": deploy_result,
    }
