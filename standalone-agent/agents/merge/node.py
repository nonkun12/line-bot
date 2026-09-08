"""Merge Agent: execute the commit/merge approval against the GitHub PR."""

from __future__ import annotations

import os
from typing import Any

import requests

GITHUB_API = "https://api.github.com"


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


def get_pr_state(pr_number: int) -> dict[str, Any]:
    response = requests.get(
        f"{GITHUB_API}/repos/{_repo()}/pulls/{int(pr_number)}",
        headers=_headers(),
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"GitHub PR lookup failed: HTTP {response.status_code}")
    data = response.json()
    return {
        "number": data.get("number"),
        "state": data.get("state"),
        "merged": bool(data.get("merged")),
        "mergeable": data.get("mergeable"),
        "url": data.get("html_url"),
        "head_sha": data.get("head", {}).get("sha"),
        "head_branch": data.get("head", {}).get("ref"),
        "base_branch": data.get("base", {}).get("ref"),
        "merge_commit_sha": data.get("merge_commit_sha"),
    }


def merge_approved_pr(state: dict[str, Any]) -> dict[str, Any]:
    publish_result = state.get("publish_result") or {}
    pr = publish_result.get("pr") or {}
    pr_number = pr.get("number")
    expected_commit = (state.get("commit_result") or {}).get("hash")
    expected_branch = publish_result.get("branch") or (state.get("commit_result") or {}).get("branch")
    if not pr_number:
        return {"merged": False, "error": "pull request number is missing"}

    current = get_pr_state(int(pr_number))
    if current.get("merged"):
        return {"merged": True, "already_merged": True, "pr": current}
    if current.get("state") != "open":
        return {"merged": False, "error": "GitHub PR is not open", "pr": current}

    if expected_branch and current.get("head_branch") != expected_branch:
        return {
            "merged": False,
            "error": "GitHub PR head branch does not match the Job branch",
            "pr": current,
        }
    if expected_commit and current.get("head_sha") != expected_commit:
        return {
            "merged": False,
            "error": "GitHub PR head commit does not match the approved Job commit",
            "pr": current,
        }
    if current.get("base_branch") != "main":
        return {
            "merged": False,
            "error": "GitHub PR base branch is not main",
            "pr": current,
        }

    response = requests.put(
        f"{GITHUB_API}/repos/{_repo()}/pulls/{int(pr_number)}/merge",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"merge_method": "squash"},
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        detail = response.text[:500]
        return {
            "merged": False,
            "error": f"GitHub PR merge failed: HTTP {response.status_code}: {detail}",
            "pr": current,
        }

    payload = response.json()
    if not payload.get("merged"):
        return {
            "merged": False,
            "error": payload.get("message") or "GitHub did not merge the PR",
            "pr": current,
        }

    verified = get_pr_state(int(pr_number))
    if not verified.get("merged"):
        return {
            "merged": False,
            "error": "GitHub merge response was not confirmed by follow-up read",
            "pr": verified,
        }

    return {"merged": True, "already_merged": False, "pr": verified}


def merge_node(state: dict[str, Any]) -> dict[str, Any]:
    results = dict(state.get("agent_results", {}))
    try:
        merge_result = merge_approved_pr(state)
    except Exception as exc:
        merge_result = {"merged": False, "error": str(exc)}
    results["merge"] = merge_result
    return {**state, "agent_results": results, "merge_result": merge_result}
