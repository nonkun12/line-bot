"""Bounded Obsidian failure -> distributed-loop dispatch.

Only sanitized failure categories and exception class names cross into GitHub.
No vault content, note text, credentials, or raw exception messages are sent.
"""
from __future__ import annotations

import os
import re
import threading
import time

import httpx

WORKFLOW = "distributed-autonomous-loop.yml"
AUTOREPAIR_INCIDENT_CATEGORIES = frozenset({"local_job_failed", "vault_write_failed"})
AUTOREPAIR_EXCEPTION_NAMES = frozenset({
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "IsADirectoryError",
    "NotADirectoryError",
    "RuntimeError",
    "ValueError",
    "TypeError",
    "KeyError",
    "AttributeError",
    "UnicodeDecodeError",
})
AUTOREPAIR_COOLDOWN_SECONDS = 30 * 60
_ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress", "requested", "waiting", "pending"})
_DISPATCH_LOCK = threading.Lock()
_LAST_DISPATCH_AT: dict[str, float] = {}


def is_repairable_obsidian_incident(category: object, detail: object) -> bool:
    """Accept only a known failure class, never arbitrary diagnostic text."""
    return (
        isinstance(category, str)
        and category in AUTOREPAIR_INCIDENT_CATEGORIES
        and isinstance(detail, str)
        and detail in AUTOREPAIR_EXCEPTION_NAMES
    )


def request_obsidian_incident_repair(
    category: str,
    detail: str,
    job_id: int | None = None,
) -> tuple[bool, str]:
    """Request one short, path-scoped repair run; never merge or deploy."""
    if not is_repairable_obsidian_incident(category, detail):
        return False, "incident_not_eligible"
    if job_id is not None and (
        not isinstance(job_id, int)
        or isinstance(job_id, bool)
        or job_id <= 0
        or job_id > 2**31 - 1
    ):
        return False, "invalid_job_id"

    repo = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return False, "repository_not_allowed"
    token = (
        os.environ.get("GITHUB_ACTIONS_DISPATCH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    ).strip()
    if not token:
        return False, "dispatch_token_missing"

    # The category-wide cooldown prevents retries from turning a persistent
    # filesystem/configuration issue into a stream of hosted AI runs.
    with _DISPATCH_LOCK:
        now = time.monotonic()
        last_dispatch = _LAST_DISPATCH_AT.get(category)
        if last_dispatch is not None and now - last_dispatch < AUTOREPAIR_COOLDOWN_SECONDS:
            return False, "cooldown_active"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        base_url = f"https://api.github.com/repos/{repo}"
        try:
            with httpx.Client(timeout=3.0, follow_redirects=False) as client:
                runs_response = client.get(
                    f"{base_url}/actions/workflows/{WORKFLOW}/runs",
                    params={"branch": "main", "per_page": 10},
                    headers=headers,
                )
                runs_response.raise_for_status()
                payload = runs_response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs", []), list):
                    return False, "workflow_status_invalid"
                if any(
                    isinstance(run, dict)
                    and run.get("status") in _ACTIVE_RUN_STATUSES
                    for run in payload.get("workflow_runs", [])
                ):
                    return False, "loop_already_running"

                dispatch_response = client.post(
                    f"{base_url}/actions/workflows/{WORKFLOW}/dispatches",
                    json={
                        "ref": "main",
                        "inputs": {
                            "max_tasks": "2",
                            "mode": "obsidian_incident",
                            "incident_category": category,
                            "incident_detail": detail,
                            "incident_job_id": str(job_id or ""),
                        },
                    },
                    headers=headers,
                )
                if dispatch_response.status_code != 204:
                    return False, f"dispatch_http_{dispatch_response.status_code}"
                _LAST_DISPATCH_AT[category] = time.monotonic()
                return True, "dispatch_accepted"
        except httpx.HTTPStatusError as exc:
            # Keep HTTP diagnostics numeric: never include response bodies or headers.
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(status_code, int) and 100 <= status_code <= 599:
                return False, f"github_http_{status_code}"
            return False, "github_http_error"
        except httpx.HTTPError as exc:
            # Exception text may contain URLs; keep logs to a safe class name.
            return False, type(exc).__name__


__all__ = [
    "AUTOREPAIR_INCIDENT_CATEGORIES",
    "AUTOREPAIR_EXCEPTION_NAMES",
    "is_repairable_obsidian_incident",
    "request_obsidian_incident_repair",
]
