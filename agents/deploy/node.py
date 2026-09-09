"""Deploy Agent with GitHub PR merge-state verification."""

from __future__ import annotations

import os
from typing import Any

import requests

from job_lease import require_active_job_lease
from render_client import trigger_deploy

GITHUB_API = "https://api.github.com"


def _auto_deploy_enabled() -> bool:
    return os.environ.get("AUTO_DEPLOY", "false").lower() == "true"


def _repo() -> str:
    return (
        os.environ.get("GITHUB_REPO")
        or os.environ.get("AI_REPORT_GITHUB_REPO")
        or "nonkun12/line-bot"
    )


def _github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def check_pr_merged(state: dict[str, Any]) -> dict[str, Any]:
    """Read GitHub's authoritative PR state before allowing deployment."""
    publish_result = state.get("publish_result") or {}
    pr = publish_result.get("pr") or {}
    pr_number = pr.get("number")
    if not pr_number:
        return {"known": False, "merged": False, "reason": "pull request number is missing"}

    url = f"{GITHUB_API}/repos/{_repo()}/pulls/{int(pr_number)}"
    response = requests.get(url, headers=_github_headers(), timeout=15)
    if response.status_code != 200:
        return {
            "known": False,
            "merged": False,
            "reason": f"GitHub PR lookup failed: HTTP {response.status_code}",
        }
    data = response.json()
    return {
        "known": True,
        "merged": bool(data.get("merged")),
        "state": data.get("state"),
        "number": data.get("number"),
        "url": data.get("html_url"),
        "merge_commit_sha": data.get("merge_commit_sha"),
    }


def deploy_node(state):
    results = dict(state.get("agent_results", {}))
    commit_result = state.get("commit_result", {})

    if not commit_result.get("committed"):
        deploy_result = {
            "deployed": False,
            "skipped": True,
            "reason": "commit not completed",
        }
        results["deploy"] = deploy_result
        return {**state, "agent_results": results, "deploy_result": deploy_result}

    is_job_flow = bool(state.get("job_id")) or bool(state.get("publish_result"))
    if not is_job_flow:
        if not _auto_deploy_enabled():
            deploy_result = {
                "deployed": False,
                "pending": True,
                "reason": "waiting for manual approval",
                "commit_hash": commit_result.get("hash"),
            }
            results["deploy"] = deploy_result
            return {**state, "agent_results": results, "deploy_result": deploy_result}

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
        return {**state, "agent_results": results, "deploy_result": deploy_result}

    try:
        merge_state = check_pr_merged(state)
    except Exception as exc:
        merge_state = {"known": False, "merged": False, "reason": str(exc)}

    if not merge_state.get("known"):
        deploy_result = {
            "deployed": False,
            "pending": True,
            "waiting_for_merge": True,
            "reason": merge_state.get("reason"),
            "commit_hash": commit_result.get("hash"),
        }
        results["deploy"] = deploy_result
        return {**state, "agent_results": results, "deploy_result": deploy_result}

    if not merge_state.get("merged"):
        deploy_result = {
            "deployed": False,
            "pending": True,
            "waiting_for_merge": True,
            "reason": "GitHub PR is not merged",
            "pr": merge_state,
            "commit_hash": commit_result.get("hash"),
        }
        results["deploy"] = deploy_result
        return {**state, "agent_results": results, "deploy_result": deploy_result}

    if not _auto_deploy_enabled():
        deploy_result = {
            "deployed": False,
            "pending": True,
            "reason": "waiting for manual deployment",
            "merged": True,
            "pr": merge_state,
            "commit_hash": commit_result.get("hash"),
        }
        results["deploy"] = deploy_result
        return {**state, "agent_results": results, "deploy_result": deploy_result}

    # Re-check the Job lease immediately before the irreversible Render trigger.
    require_active_job_lease(state)
    trigger_result = trigger_deploy()
    deploy_result = {
        "deployed": trigger_result.get("triggered", False),
        "pending": False,
        "deploy_id": trigger_result.get("deploy_id"),
        "status": trigger_result.get("status"),
        "merged": True,
        "pr": merge_state,
        "commit_hash": commit_result.get("hash"),
    }
    if not trigger_result.get("triggered"):
        deploy_result["reason"] = trigger_result.get("error")

    results["deploy"] = deploy_result
    return {**state, "agent_results": results, "deploy_result": deploy_result}
