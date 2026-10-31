"""Read-only poller for the private Hermes GitHub Issues queue.

This first-stage worker only discovers and classifies queue items. It never
claims, executes, comments on, closes, merges, or deploys an issue.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import httpx


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_TITLE_RE = re.compile(r"^Hermes task ([0-9a-f]{32})$")
_REQUESTER_RE = re.compile(r"^- requester_user_id: ([^\r\n]{1,128})$", re.MULTILINE)
_APPROVAL_RE = re.compile(r"^- approval_state: (not_approved|approved)$", re.MULTILINE)
_MAX_ISSUES = 50


class WorkerConfigurationError(RuntimeError):
    pass


class WorkerFetchError(RuntimeError):
    pass


def classify_issue(issue: dict[str, Any]) -> dict[str, str] | None:
    """Return safe metadata only; never return or execute the instruction body."""
    if issue.get("pull_request") or issue.get("state") != "open":
        return None
    title = issue.get("title")
    match = _TASK_TITLE_RE.fullmatch(title if isinstance(title, str) else "")
    if not match:
        return None
    body = issue.get("body")
    if not isinstance(body, str):
        return None
    requester = _REQUESTER_RE.search(body)
    approval = _APPROVAL_RE.search(body)
    if not requester or not approval:
        return {
            "task_id": match.group(1),
            "issue_number": str(issue.get("number", "")),
            "state": "blocked_invalid_metadata",
        }
    return {
        "task_id": match.group(1),
        "issue_number": str(issue.get("number", "")),
        "requester_user_id": requester.group(1),
        "state": "ready_for_manual_approval" if approval.group(1) == "approved" else "blocked_not_approved",
    }


def fetch_queue(
    *,
    token: str | None = None,
    repository: str | None = None,
) -> list[dict[str, str]]:
    """Fetch open queue items in read-only mode."""
    token = (token if token is not None else os.environ.get("GH_QUEUE_TOKEN", "")).strip()
    repository = (
        repository if repository is not None else os.environ.get("GH_QUEUE_REPOSITORY", "")
    ).strip()
    if not token:
        raise WorkerConfigurationError("GH_QUEUE_TOKEN is not configured")
    if not _REPOSITORY_RE.fullmatch(repository):
        raise WorkerConfigurationError("GH_QUEUE_REPOSITORY must be owner/name")

    response = httpx.get(
        f"https://api.github.com/repos/{repository}/issues",
        params={"state": "open", "per_page": _MAX_ISSUES},
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        raise WorkerFetchError(f"GitHub queue read failed: HTTP {response.status_code}")
    try:
        issues = response.json()
    except ValueError as exc:
        raise WorkerFetchError("GitHub returned invalid JSON") from exc
    if not isinstance(issues, list):
        raise WorkerFetchError("GitHub returned an unexpected queue response")
    tasks = [task for issue in issues if isinstance(issue, dict)
             if (task := classify_issue(issue)) is not None]
    return sorted(tasks, key=lambda task: int(task["issue_number"] or 0))


def main() -> int:
    try:
        tasks = fetch_queue()
    except WorkerConfigurationError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except WorkerFetchError as exc:
        print(f"FETCH_ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "mode": "read_only",
        "execution_enabled": False,
        "task_count": len(tasks),
        "tasks": tasks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
