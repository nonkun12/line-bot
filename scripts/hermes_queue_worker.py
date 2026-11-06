"""Single-Mac, approval-gated GitHub Issues poller for Hermes.

The worker can discover and claim approved tasks, but deliberately cannot
execute instructions, close issues, merge pull requests, or deploy.
Only one process on this Mac may claim at a time (fcntl lock).
"""
from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl
import httpx


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_TITLE_RE = re.compile(r"^Hermes task ([0-9a-f]{32})$")
_REQUESTER_RE = re.compile(r"^- requester_user_id: ([^\r\n]{1,128})$", re.MULTILINE)
_APPROVAL_RE = re.compile(r"^- approval_state: (not_approved|approved)$", re.MULTILINE)
_QUEUE_STATE_RE = re.compile(r"^- queue_state: (pending|claimed|running|completed|blocked|failed)$", re.MULTILINE)
_MAX_ISSUES = 50
_QUEUE_REPOSITORY = "nonkun12/ai-dispatch-queue"


def _allowed_requesters() -> set[str]:
    configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    return {item.strip() for item in configured.split(",") if item.strip()}


def _trusted_requester(body: str) -> str | None:
    values = _REQUESTER_RE.findall(body)
    allowed = _allowed_requesters()
    if len(values) != 1 or not allowed or values[0] not in allowed:
        return None
    return values[0]


class WorkerConfigurationError(RuntimeError):
    pass


class WorkerFetchError(RuntimeError):
    pass


class WorkerAlreadyRunning(RuntimeError):
    pass


class ClaimRejected(RuntimeError):
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
    requester = _trusted_requester(body)
    approvals = _APPROVAL_RE.findall(body)
    queue_states = _QUEUE_STATE_RE.findall(body)
    if requester is None or len(approvals) != 1 or len(queue_states) != 1:
        return {
            "task_id": match.group(1),
            "issue_number": str(issue.get("number", "")),
            "state": "blocked_invalid_metadata",
        }
    state = queue_states[0]
    if state != "pending":
        result_state = f"blocked_{state}"
    elif approvals[0] != "approved":
        result_state = "blocked_not_approved"
    else:
        result_state = "ready_for_manual_approval"
    return {
        "task_id": match.group(1),
        "issue_number": str(issue.get("number", "")),
        "requester_user_id": requester,
        "state": result_state,
    }


def _credentials(token: str | None, repository: str | None) -> tuple[str, str]:
    token = (token if token is not None else os.environ.get("GH_QUEUE_TOKEN", "")).strip()
    repository = (
        repository if repository is not None else os.environ.get("GH_QUEUE_REPOSITORY", "")
    ).strip()
    if not token:
        raise WorkerConfigurationError("GH_QUEUE_TOKEN is not configured")
    if repository != _QUEUE_REPOSITORY:
        raise WorkerConfigurationError("GH_QUEUE_REPOSITORY must target the configured private queue repository")
    return token, repository


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@contextmanager
def single_worker_lock(lock_path: str | Path | None = None) -> Iterator[None]:
    """Prevent two worker processes on this Mac from claiming simultaneously."""
    path = Path(lock_path) if lock_path else Path.home() / ".cache" / "hermes-queue-worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkerAlreadyRunning("another Hermes queue worker holds the local lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def fetch_queue(
    *,
    token: str | None = None,
    repository: str | None = None,
) -> list[dict[str, str]]:
    """Fetch open queue items and return safe metadata only."""
    token, repository = _credentials(token, repository)
    response = httpx.get(
        f"https://api.github.com/repos/{repository}/issues",
        params={"state": "open", "per_page": _MAX_ISSUES},
        headers=_headers(token),
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


def claim_approved_issue(
    issue_number: int,
    *,
    worker_id: str,
    token: str | None = None,
    repository: str | None = None,
    lock_path: str | Path | None = None,
) -> dict[str, str]:
    """Claim an approved pending issue while holding the designated-Mac lock.

    The lock serializes all claim callers on this Mac. It is not a distributed
    lock; deployments must keep exactly one designated worker host.
    """
    with single_worker_lock(lock_path):
        return _claim_approved_issue_locked(
            issue_number,
            worker_id=worker_id,
            token=token,
            repository=repository,
        )


def _claim_approved_issue_locked(
    issue_number: int,
    *,
    worker_id: str,
    token: str | None = None,
    repository: str | None = None,
) -> dict[str, str]:
    """Read, validate and update one issue; caller must hold the local lock."""
    token, repository = _credentials(token, repository)
    worker_id = str(worker_id or "").strip()
    if not worker_id or len(worker_id) > 128 or "\n" in worker_id:
        raise ValueError("worker_id must be a non-empty single-line value")

    base = f"https://api.github.com/repos/{repository}/issues/{int(issue_number)}"
    current = httpx.get(base, headers=_headers(token), timeout=10.0)
    if current.status_code != 200:
        raise WorkerFetchError(f"GitHub issue read failed: HTTP {current.status_code}")
    try:
        issue = current.json()
    except ValueError as exc:
        raise WorkerFetchError("GitHub returned invalid issue JSON") from exc
    if not isinstance(issue, dict) or issue.get("pull_request") or issue.get("state") != "open":
        raise ClaimRejected("queue item is not an open issue")

    body = issue.get("body")
    title = issue.get("title")
    if not isinstance(body, str) or not isinstance(title, str):
        raise ClaimRejected("queue item metadata is invalid")
    if not _TASK_TITLE_RE.fullmatch(title):
        raise ClaimRejected("issue is not a Hermes queue task")

    requester = _trusted_requester(body)
    approvals = _APPROVAL_RE.findall(body)
    states = _QUEUE_STATE_RE.findall(body)
    if requester is None:
        raise ClaimRejected("requester is missing or not allowlisted")
    if len(approvals) != 1 or approvals[0] != "approved":
        raise ClaimRejected("exactly one explicit approval marker is required")
    if len(states) != 1 or states[0] != "pending":
        raise ClaimRejected("exactly one pending queue-state marker is required")

    claimed_at = datetime.now(timezone.utc).isoformat()
    updated = _QUEUE_STATE_RE.sub("- queue_state: claimed", body, count=1)
    updated += f"\n- worker_id: {worker_id}\n- claimed_at: {claimed_at}\n"
    response = httpx.patch(
        base,
        json={"body": updated},
        headers=_headers(token),
        timeout=10.0,
    )
    if response.status_code != 200:
        raise WorkerFetchError(f"GitHub issue claim failed: HTTP {response.status_code}")
    return {
        "task_id": _TASK_TITLE_RE.fullmatch(title).group(1),
        "issue_number": str(issue_number),
        "state": "claimed_not_executed",
    }


def main() -> int:
    try:
        with single_worker_lock():
            tasks = fetch_queue()
    except WorkerAlreadyRunning as exc:
        print(f"LOCKED: {exc}", file=sys.stderr)
        return 3
    except WorkerConfigurationError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except WorkerFetchError as exc:
        print(f"FETCH_ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "mode": "single_worker_read_only",
        "execution_enabled": False,
        "claiming_enabled": False,
        "task_count": len(tasks),
        "tasks": tasks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
