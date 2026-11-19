"""Server-side queue contract for the Mac-local Obsidian bridge.

The cloud side never touches the Obsidian vault. It only queues explicit
Obsidian commands for an authenticated Mac bridge to claim and execute locally.
"""
from __future__ import annotations

import os

from .obsidian import ObsidianError
from agents.obsidian.intents import is_obsidian_intent, normalize_obsidian_command
from db import create_job

OBSIDIAN_JOB_TYPE = "obsidian"
MAX_OBSIDIAN_MESSAGE_CHARS = 4000


def enqueue_obsidian_request(user_id: str, message: str) -> int:
    """Queue one explicit Obsidian request for the Mac bridge."""
    normalized_user_id = str(user_id or "").strip()
    raw_message = str(message or "").strip()
    if not normalized_user_id:
        raise ObsidianError("user_id is required")
    if len(normalized_user_id) > 200:
        raise ObsidianError("user_id exceeds 200 characters")
    if not raw_message:
        raise ObsidianError("Obsidian message is required")
    if len(raw_message) > MAX_OBSIDIAN_MESSAGE_CHARS:
        raise ObsidianError("Obsidian message exceeds 4000 characters")
    normalized_message = normalize_obsidian_command(raw_message)
    if normalized_message is None:
        raise ObsidianError("only explicit Obsidian commands may be queued")
    if len(normalized_message) > MAX_OBSIDIAN_MESSAGE_CHARS:
        raise ObsidianError("Obsidian message exceeds 4000 characters")
    if not is_obsidian_intent(normalized_message):
        raise ObsidianError("only explicit Obsidian commands may be queued")
    if not os.environ.get("OBSIDIAN_BRIDGE_KEY", "").strip():
        raise ObsidianError("Obsidian Mac bridge is not configured")
    job_id = create_job(
        normalized_user_id,
        normalized_message,
        job_type=OBSIDIAN_JOB_TYPE,
        source="line",
        max_retries=3,
    )
    if not isinstance(job_id, int) or job_id <= 0:
        raise ObsidianError("failed to create Obsidian job")
    return job_id


__all__ = ["MAX_OBSIDIAN_MESSAGE_CHARS", "OBSIDIAN_JOB_TYPE", "enqueue_obsidian_request"]
