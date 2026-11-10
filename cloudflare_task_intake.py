"""Opt-in, approval-only LINE intake into the Cloudflare D1 task ledger.

This module only persists explicitly prefixed requests. It never starts GitHub
Actions, creates PRs, edits code, or executes queued tasks.
"""
from __future__ import annotations

import hashlib
import os
from urllib.parse import urlsplit

import httpx


_PREFIXES = ("D1登録:", "タスク登録:", "Cloudflare登録:")
_MAX_REQUEST_CHARS = 2000


def extract_intake_request(message: str) -> str | None:
    """Return the body of an explicit intake command, or None for other chat."""
    if not isinstance(message, str):
        return None
    for prefix in _PREFIXES:
        if message.startswith(prefix):
            return message[len(prefix):].strip()
    return None


def _enabled() -> bool:
    return os.environ.get("CLOUDFLARE_TASK_INTAKE_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _allowed_user_ids() -> set[str]:
    raw = os.environ.get("CLOUDFLARE_TASK_INTAKE_LINE_USER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _valid_api_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def submit_line_task(*, message_id: str, user_id: str, request_text: str) -> dict[str, object]:
    """Persist one explicit LINE request; fail closed on missing config/errors."""
    if not _enabled():
        return {"ok": False, "error": "disabled"}

    allowed = _allowed_user_ids()
    if not user_id or user_id not in allowed:
        return {"ok": False, "error": "not_allowed"}

    api_url = os.environ.get("CLOUDFLARE_TASK_API_URL", "").strip().rstrip("/")
    api_token = os.environ.get("CLOUDFLARE_TASK_API_TOKEN", "")
    if not api_url or not api_token or not _valid_api_url(api_url):
        return {"ok": False, "error": "missing_config"}

    if (
        not message_id
        or len(message_id) > 200
        or not isinstance(request_text, str)
        or not request_text.strip()
        or len(request_text) > _MAX_REQUEST_CHARS
    ):
        return {"ok": False, "error": "invalid_request"}

    # Stable ID lets an explicit user retry safely after a network timeout.
    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:40]
    task_id = f"line-{digest}"
    payload = {
        "task_id": task_id,
        "request_text": request_text.strip(),
        "source_event_id": message_id,
    }

    try:
        response = httpx.post(
            f"{api_url}/tasks",
            headers={"Authorization": f"Bearer {api_token}"},
            json=payload,
            timeout=5.0,
        )
        if response.status_code not in (200, 201):
            return {"ok": False, "error": "api_rejected", "http_status": response.status_code}

        data = response.json()
        task = data.get("task") if isinstance(data, dict) else None
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            return {"ok": False, "error": "api_rejected"}

        return {
            "ok": True,
            "task_id": task_id,
            "duplicate": bool(data.get("duplicate", not data.get("created", False))),
        }
    except (httpx.HTTPError, ValueError, TypeError):
        # Do not log headers, URL credentials, or request contents.
        return {"ok": False, "error": "network_error"}
