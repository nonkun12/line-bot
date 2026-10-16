"""Queue contract for isolated Mac-local code-review jobs.

This module deliberately does not share Obsidian command normalization or
execution. It only creates a bounded review request; a separately authenticated
local worker must validate the SHA values against its checkout before running fm.
"""
from __future__ import annotations

import json
import re

from db import create_job, get_conn

REVIEW_JOB_TYPE = "local_code_review"
REVIEW_SCHEMA_VERSION = 1
MAX_REPOSITORY_CHARS = 200
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_REPOSITORIES = {"nonkun12/line-bot"}


def build_review_payload(repository: str, base_sha: str, head_sha: str) -> str:
    """Validate and serialize a minimal review request; reject arbitrary paths/commands."""
    if not isinstance(repository, str) or repository not in _ALLOWED_REPOSITORIES:
        raise ValueError("repository is not allowlisted")
    if len(repository) > MAX_REPOSITORY_CHARS:
        raise ValueError("repository exceeds maximum length")
    if not isinstance(base_sha, str) or not _SHA_RE.fullmatch(base_sha):
        raise ValueError("base_sha must be a full lowercase git SHA")
    if not isinstance(head_sha, str) or not _SHA_RE.fullmatch(head_sha):
        raise ValueError("head_sha must be a full lowercase git SHA")
    if base_sha == head_sha:
        raise ValueError("base_sha and head_sha must differ")
    return json.dumps(
        {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "kind": REVIEW_JOB_TYPE,
            "repository": repository,
            "base_sha": base_sha,
            "head_sha": head_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def enqueue_local_review(user_id: str, repository: str, base_sha: str, head_sha: str) -> int:
    """Create one bounded review job; never runs a reviewer or changes code."""
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id or len(normalized_user_id) > 200:
        raise ValueError("user_id must contain 1..200 characters")
    payload = build_review_payload(repository, base_sha, head_sha)

    # LINE redelivery/repeated commands should reuse an active identical job.
    # BEGIN IMMEDIATE serializes the check/insert sequence across SQLite writers.
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT id FROM jobs
            WHERE user_id=? AND job_type=? AND message=? AND status IN ('pending', 'running')
            ORDER BY id LIMIT 1
            """,
            (normalized_user_id, REVIEW_JOB_TYPE, payload),
        ).fetchone()
        if existing is not None:
            return int(existing[0])
        cursor = conn.execute(
            """
            INSERT INTO jobs(user_id, job_type, source, parent_job_id, message, status, max_retries)
            VALUES (?, ?, 'control_tower', NULL, ?, 'pending', 1)
            """,
            (normalized_user_id, REVIEW_JOB_TYPE, payload),
        )
        job_id = cursor.lastrowid
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("failed to create local review job")
    return job_id


__all__ = [
    "REVIEW_JOB_TYPE",
    "REVIEW_SCHEMA_VERSION",
    "build_review_payload",
    "enqueue_local_review",
]
