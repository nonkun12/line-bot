"""Fail-closed contract for a future ORCA distributed-loop intake route.

This module deliberately does not perform network I/O or register tasks. The
D1 schema and worker must support the explicit task_type before this payload
may be sent to the API.
"""
from __future__ import annotations

import re
from typing import Any

from distributed_loop_trigger import _requested_max_tasks

_LINE_USER_ID_RE = re.compile(r"^U[0-9a-fA-F]{32}$")


def build_distributed_loop_task_payload(
    *,
    task_id: str,
    request_text: str,
    source_event_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """Build a typed, owner-bound payload for an explicitly recognized loop command.

    No dispatch, approval, claim, or execution occurs here. The caller must not
    POST this payload until the D1 API has an enforced task_type discriminator
    and the worker has a matching distributed_loop execution handler.
    """
    if not isinstance(user_id, str) or _LINE_USER_ID_RE.fullmatch(user_id) is None:
        raise ValueError("verified LINE user ID is required")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
        raise ValueError("invalid ORCA task ID")
    if not isinstance(source_event_id, str) or not source_event_id.strip():
        raise ValueError("LINE source event ID is required")
    if not isinstance(request_text, str) or not request_text.strip():
        raise ValueError("distributed-loop command is required")

    max_tasks = _requested_max_tasks(request_text)
    if max_tasks is None:
        raise ValueError("unrecognized distributed-loop command or missing safety confirmation")

    return {
        "task_id": task_id,
        "task_type": "distributed_loop",
        "request_text": request_text,
        "max_tasks": max_tasks,
        "source_event_id": source_event_id,
        "user_id": user_id,
    }
