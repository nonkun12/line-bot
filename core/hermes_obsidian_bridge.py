"""Fail-closed boundary for forwarding verified Hermes results to the Obsidian queue.

This module deliberately does not execute Hermes, apply patches, deploy, or write to
the Obsidian vault. A verified result may only become an authenticated pending job
for the existing Mac-local Obsidian bridge.
"""
from __future__ import annotations

from typing import Mapping

from .obsidian_bridge import enqueue_obsidian_request

PASS_STATUS = "PASS"
ALLOWED_SOURCE = "hermes-kanban"
MAX_HERMES_SUMMARY_CHARS = 2000


def is_verified_hermes_result(result: Mapping[str, object]) -> bool:
    """Return True only for an explicitly verified Hermes PASS result."""
    if not isinstance(result, Mapping):
        return False
    if result.get("source") != ALLOWED_SOURCE:
        return False
    if result.get("status") != PASS_STATUS:
        return False
    if result.get("verified") is not True:
        return False
    if result.get("auto_apply_patch") is not False:
        return False
    if result.get("auto_deploy") is not False:
        return False
    return True


def enqueue_verified_hermes_result(
    user_id: str, result: Mapping[str, object]
) -> int:
    """Queue a verified Hermes PASS as an Obsidian pending job.

    This is the only handoff point. It never executes Hermes or writes to the
    vault; the existing authenticated Mac bridge remains responsible for that.
    """
    if not is_verified_hermes_result(result):
        raise ValueError("Hermes result is not verified and safe to queue")

    task_id = str(result.get("task_id") or "").strip()
    summary = str(result.get("summary") or "").strip()
    if not task_id or not summary:
        raise ValueError("verified Hermes result requires task_id and summary")
    if len(task_id) > 200:
        raise ValueError("task_id exceeds 200 characters")
    if len(summary) > MAX_HERMES_SUMMARY_CHARS:
        raise ValueError("summary exceeds 2000 characters")

    message = f"Obsidianに追記 LINE-Inbox.md: Hermes PASS {task_id}: {summary}"
    return enqueue_obsidian_request(user_id, message)


__all__ = [
    "ALLOWED_SOURCE",
    "MAX_HERMES_SUMMARY_CHARS",
    "PASS_STATUS",
    "enqueue_verified_hermes_result",
    "is_verified_hermes_result",
]
