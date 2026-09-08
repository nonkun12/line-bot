"""Verify GitHub CI/review checks before the merge approval gate."""

from __future__ import annotations

import os
from typing import Any

import requests

GITHUB_API = "https://api.github.com"
REQUIRED_WORKFLOWS = ("Pytest", "Overnight Worker Test", "AI Code Review")


def _repo() -> str:
    return (
        os.environ.get("GITHUB_REPO")
        or os.environ.get("AI_REPORT_GITHUB_REPO")
        or "nonkun12/line-bot"
    )


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _head_sha(state: dict[str, Any]) -> str | None:
    publish = state.get("publish_result") or {}
    commit = state.get("commit_result") or {}
    return commit.get("hash") or publish.get("commit_hash")


def check_review_status(state: dict[str, Any]) -> dict[str, Any]:
    """Check all required GitHub workflow results for the Job commit."""
    head_sha = _head_sha(state)
    if not head_sha:
        return {"status": "failed", "reason": "approved Job commit hash is missing"}

    response = requests.get(
        f"{GITHUB_API}/repos/{_repo()}/actions/runs",
        headers=_headers(),
        params={"head_sha": head_sha, "per_page": 50},
        timeout=15,
    )
    if response.status_code != 200:
        return {"status": "pending", "reason": f"GitHub workflow lookup failed: HTTP {response.status_code}"}

    runs = response.json()
    by_name: dict[str, dict[str, Any]] = {}
    if isinstance(runs, dict):
        runs = runs.get("workflow_runs", [])
    for run in runs if isinstance(runs, list) else []:
        name = run.get("name")
        if name in REQUIRED_WORKFLOWS and name not in by_name:
            by_name[name] = run

    missing = [name for name in REQUIRED_WORKFLOWS if name not in by_name]
    if missing:
        return {"status": "pending", "reason": "required GitHub review checks are not present", "missing": missing}

    pending = [
        name for name, run in by_name.items()
        if run.get("status") != "completed"
    ]
    if pending:
        return {"status": "pending", "reason": "required GitHub review checks are still running", "pending": pending}

    failed = [
        name for name, run in by_name.items()
        if run.get("conclusion") not in {"success", "neutral", "skipped"}
    ]
    if failed:
        return {
            "status": "failed",
            "reason": "one or more required GitHub review checks failed",
            "failed": failed,
        }

    return {
        "status": "passed",
        "head_sha": head_sha,
        "workflows": {
            name: {
                "run_id": run.get("id"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
            }
            for name, run in by_name.items()
        },
    }


def review_node(state: dict[str, Any]) -> dict[str, Any]:
    results = dict(state.get("agent_results", {}))
    try:
        review_result = check_review_status(state)
    except Exception as exc:
        review_result = {"status": "pending", "reason": str(exc)}
    results["review"] = review_result
    return {**state, "agent_results": results, "review_result": review_result}
