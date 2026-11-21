"""Helpers for safely attaching verified LINE identity to ORCA task intake."""

import re
from typing import Any

_LINE_USER_ID_RE = re.compile(r"^U[0-9a-fA-F]{32}$")


def build_task_payload(
    task_id: str,
    request_text: str,
    message_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Build an intake payload only when the verified LINE owner is present.

    Creating an ownerless task would make the later same-user approval and
    owner-scoped status protocol impossible to enforce. Fail closed instead of
    silently dropping an absent or malformed identity.
    """
    if not isinstance(user_id, str) or _LINE_USER_ID_RE.fullmatch(user_id) is None:
        raise ValueError("verified LINE user ID is required for ORCA task intake")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
        raise ValueError("invalid ORCA task ID")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("LINE source event ID is required")
    if not isinstance(request_text, str) or not request_text.strip():
        raise ValueError("ORCA task request text is required")
    if not request_text.startswith(("アプリ開発:", "アプリ開発：")):
        raise ValueError("only explicit アプリ開発: tasks are accepted")
    return {
        "task_id": task_id,
        "request_text": request_text,
        "source_event_id": message_id,
        "user_id": user_id,
    }
