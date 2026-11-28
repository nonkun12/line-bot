"""Fail-closed reader for the owner-operated Global HOLD GitHub issue."""
from __future__ import annotations

from typing import Any

CONTROL_TITLE = "[CONTROL] Autonomous Loop Global HOLD"
CONTROL_MARKER = "<!-- GLOBAL_HOLD_CONTROL: v1 -->"
CONTROL_OWNER = "nonkun12"
CONTROL_ISSUE_NUMBER = 1786


def evaluate_global_hold_issue(
    payload: Any,
    *,
    issue_number: int = CONTROL_ISSUE_NUMBER,
    owner: str = CONTROL_OWNER,
) -> dict[str, str]:
    """Return a scheduler gate decision from one exact GitHub issue payload.

    OPEN always means HOLD. CLEAR requires the exact control issue, its original
    owner-authored identity marker, and a completed close performed by the repo
    owner. Missing, malformed, ambiguous, or unexpected data blocks execution.
    """
    blocked = {"dispatch": "false", "decision": "SKIPPED_GLOBAL_HOLD_UNVERIFIED", "state": "UNKNOWN_BLOCKED"}
    if not isinstance(payload, dict):
        return blocked
    if type(issue_number) is not int or issue_number != CONTROL_ISSUE_NUMBER:
        return blocked
    if payload.get("number") != issue_number or isinstance(payload.get("number"), bool):
        return blocked
    if payload.get("title") != CONTROL_TITLE or "pull_request" in payload:
        return blocked
    creator = payload.get("user")
    if not isinstance(creator, dict) or creator.get("login") != owner:
        return blocked
    body = payload.get("body")
    if not isinstance(body, str) or body.count(CONTROL_MARKER) != 1:
        return blocked

    state = payload.get("state")
    if state == "open":
        return {"dispatch": "false", "decision": "SKIPPED_GLOBAL_HOLD_ACTIVE", "state": "HOLD"}
    if state != "closed":
        return blocked

    closed_by = payload.get("closed_by")
    if (
        not isinstance(closed_by, dict)
        or closed_by.get("login") != owner
        or payload.get("state_reason") != "completed"
        or not isinstance(payload.get("closed_at"), str)
        or not payload["closed_at"].strip()
    ):
        return blocked

    return {"dispatch": "true", "decision": "GLOBAL_HOLD_CLEAR", "state": "CLEAR"}


__all__ = ["evaluate_global_hold_issue"]
