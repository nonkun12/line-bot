"""Durable hand-off to the private GitHub Issues queue for the local Hermes worker.

This module only enqueues tasks. It never executes, approves, merges, or deploys them.
Callers must enforce their own user allowlist before passing authorized=True.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import httpx


_MAX_INSTRUCTION_LENGTH = 2000
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_QUEUE_REPOSITORY = "nonkun12/ai-dispatch-queue"


def _is_authorized_user(user_id: str) -> bool:
    configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and user_id in allowed


class QueueConfigurationError(RuntimeError):
    """The private queue is not configured safely."""


class QueueEnqueueError(RuntimeError):
    """GitHub rejected or could not accept the queue item."""


def enqueue_hermes_task(
    instruction: str,
    *,
    user_id: str,
    authorized: bool = False,
    token: str | None = None,
    repository: str | None = None,
    request_id: str | None = None,
) -> dict[str, str]:
    """Create one pending issue in the private queue after caller authorization."""
    text = str(instruction or "").strip()
    actor = str(user_id or "").strip()
    if not authorized:
        raise PermissionError("authorized caller required")
    if not actor or len(actor) > 128 or "\\n" in actor or "\\r" in actor:
        raise ValueError("user_id must be a valid single-line identifier")
    if not _is_authorized_user(actor):
        raise PermissionError("user_id is not allowlisted")
    if not text:
        raise ValueError("instruction is required")
    if len(text) > _MAX_INSTRUCTION_LENGTH:
        raise ValueError("instruction exceeds maximum length")

    token = (token if token is not None else os.environ.get("GH_QUEUE_TOKEN", "")).strip()
    repository = (
        repository if repository is not None else os.environ.get("GH_QUEUE_REPOSITORY", "")
    ).strip()
    if not token:
        raise QueueConfigurationError("GH_QUEUE_TOKEN is not configured")
    if repository != _QUEUE_REPOSITORY:
        raise QueueConfigurationError("GH_QUEUE_REPOSITORY must target the configured private queue repository")

    task_id = request_id or uuid.uuid4().hex
    if not _REQUEST_ID_RE.fullmatch(task_id):
        raise ValueError("request_id must be a 32-character lowercase hex ID")

    created_at = datetime.now(timezone.utc).isoformat()
    title = f"Hermes task {task_id}"
    body = (
        "## Queue metadata\n"
        f"- request_id: {task_id}\n"
        f"- requester_user_id: {actor}\n"
        f"- created_at: {created_at}\n"
        "- queue_state: pending\n"
        "- approval_state: not_approved\n"
        "\n## Instruction\n"
        f"{text}\n"
        "\n## Execution policy\n"
        "This item is not approved for execution by creation. A separate authorization "
        "gate must explicitly approve it. Do not merge or deploy automatically.\n"
    )
    response = httpx.post(
        f"https://api.github.com/repos/{repository}/issues",
        json={"title": title, "body": body},
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10.0,
    )
    if response.status_code not in (200, 201):
        raise QueueEnqueueError(f"GitHub issue creation failed: HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise QueueEnqueueError("GitHub returned invalid JSON") from exc
    issue_number = payload.get("number")
    issue_url = payload.get("html_url")
    if type(issue_number) is not int or not isinstance(issue_url, str) or not issue_url.startswith("https://github.com/"):
        raise QueueEnqueueError("GitHub response omitted a valid issue reference")
    return {"task_id": task_id, "issue_number": str(issue_number), "url": issue_url}
