"""Publish a committed overnight Job branch to GitHub and create/reuse its PR."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import requests

from job_lease import require_active_job_lease

GIT_COMMAND_TIMEOUT = float(os.environ.get("GIT_COMMAND_TIMEOUT", "30.0"))
GITHUB_API = "https://api.github.com"


def _publish_enabled() -> bool:
    return os.environ.get("AUTO_PUBLISH_JOB_BRANCH", "false").lower() == "true"


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=GIT_COMMAND_TIMEOUT,
    )


def _repo() -> str:
    return os.environ.get("GITHUB_REPO") or os.environ.get("AI_REPORT_GITHUB_REPO") or "nonkun12/line-bot"


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _push_branch(workdir: str, branch: str) -> None:
    if not branch:
        raise RuntimeError("job branch is missing")
    remote = _run_git(["remote", "get-url", "origin"], cwd=workdir)
    if remote.returncode != 0 or not remote.stdout.strip():
        raise RuntimeError("git origin remote is not configured")

    token = _token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_HTTP_EXTRAHEADER"] = f"Authorization: Bearer {token}"
    result = subprocess.run(
        ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
        cwd=workdir, capture_output=True, text=True, timeout=GIT_COMMAND_TIMEOUT,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git push failed")


def _find_open_pr(branch: str) -> dict[str, Any] | None:
    owner = _repo().split("/", 1)[0]
    url = f"{GITHUB_API}/repos/{_repo()}/pulls"
    response = requests.get(
        url,
        headers=_headers(),
        params={"state": "open", "head": f"{owner}:{branch}", "base": "main", "per_page": 10},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"GitHub PR lookup failed: HTTP {response.status_code}")
    data = response.json()
    return data[0] if isinstance(data, list) and data else None


def _create_pr(branch: str, title: str, body: str) -> dict[str, Any]:
    existing = _find_open_pr(branch)
    if existing:
        return {
            "number": existing.get("number"),
            "url": existing.get("html_url"),
            "created": False,
            "state": existing.get("state"),
        }

    url = f"{GITHUB_API}/repos/{_repo()}/pulls"
    response = requests.post(
        url,
        headers={**_headers(), "Content-Type": "application/json"},
        json={"title": title, "head": branch, "base": "main", "body": body},
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        detail = response.text[:500]
        raise RuntimeError(f"GitHub PR creation failed: HTTP {response.status_code}: {detail}")
    data = response.json()
    return {
        "number": data.get("number"),
        "url": data.get("html_url"),
        "created": True,
        "state": data.get("state"),
    }


def publish_job_branch(state: dict) -> dict:
    commit_result = state.get("commit_result", {}) or {}
    workdir = state.get("workdir") or os.environ.get("REPO_WORKDIR") or os.getcwd()
    job_id = state.get("job_id")
    branch = commit_result.get("branch") or (f"worker/job-{job_id}" if job_id is not None else None)
    if not commit_result.get("committed"):
        return {"published": False, "skipped": True, "reason": "commit not completed"}
    if not _publish_enabled():
        return {
            "published": False,
            "skipped": True,
            "manual_required": True,
            "reason": "AUTO_PUBLISH_JOB_BRANCH is not enabled",
            "branch": branch,
        }

    # Re-check immediately before the first irreversible external side effect.
    require_active_job_lease(state)
    _push_branch(workdir, branch)
    # A push succeeded, but the lease may have expired while GitHub was contacted.
    # Fail closed before creating/reusing a PR as the next external mutation.
    require_active_job_lease(state)
    message = commit_result.get("message") or f"Overnight Job {job_id}"
    pr = _create_pr(
        branch,
        title=f"Overnight Job {job_id}: {message}",
        body=(
            f"Automated development Job {job_id}.\n\n"
            "This PR was created by the overnight development Worker after tests passed.\n"
            "Deployment remains behind the separate deploy approval gate."
        ),
    )
    return {
        "published": True,
        "branch": branch,
        "commit_hash": commit_result.get("hash"),
        "pr": pr,
    }


def publish_node(state: dict) -> dict:
    results = dict(state.get("agent_results", {}))
    try:
        publish_result = publish_job_branch(state)
    except Exception as exc:
        publish_result = {"published": False, "error": str(exc)}
    results["publish"] = publish_result
    return {**state, "agent_results": results, "publish_result": publish_result}
