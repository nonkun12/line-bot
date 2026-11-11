"""Helpers for safely attaching verified LINE identity to ORCA task intake."""

import re
from typing import Any

_LINE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def build_task_payload(
    task_id: str,
    request_text: str,
    message_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Build an intake payload; include only a validated LINE source user ID."""
    payload: dict[str, Any] = {
        "task_id": task_id,
        "request_text": request_text,
        "source_event_id": str(message_id),
    }
    if isinstance(user_id, str) and _LINE_USER_ID_RE.fullmatch(user_id):
        payload["user_id"] = user_id
    return payload
