"""
Phase4c: Deploy Agent

安全設計:
- commit成功後のみ起動
- AUTO_DEPLOY=true (明示的に設定された場合)のみ実際にRenderへ
  デプロイをトリガーする。デフォルト(false)では従来通り
  「承認待ち(pending)」を返すだけで、実デプロイは一切行わない。
- 実デプロイに失敗した場合もこのノードは例外を送出せず、
  失敗内容をdeploy_resultに格納して後続(finalizer)へ渡す。
"""

import os

from render_client import trigger_deploy


def _auto_deploy_enabled() -> bool:
    return os.environ.get(
        "AUTO_DEPLOY",
        "false"
    ).lower() == "true"


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


    if not _auto_deploy_enabled():

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


    # AUTO_DEPLOY=true: 実際にRenderへデプロイをトリガーする
    trigger_result = trigger_deploy()

    deploy_result = {
        "deployed": trigger_result.get("triggered", False),
        "pending": False,
        "deploy_id": trigger_result.get("deploy_id"),
        "status": trigger_result.get("status"),
        "commit_hash": commit_result.get("hash"),
    }

    if not trigger_result.get("triggered"):
        deploy_result["reason"] = trigger_result.get("error")


    results["deploy"] = deploy_result


    return {
        **state,
        "agent_results": results,
        "deploy_result": deploy_result,
    }
