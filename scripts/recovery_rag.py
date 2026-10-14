"""Safe, optional retrieval helpers for sanitized Recovery AI history.

This module stores only allowlisted outcome fields and fingerprints. It never
stores prompts, raw exception messages, test output, source code, or credentials.
Callers must supply a durable database path if history must survive process restarts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rag_store import RagStore

_ALLOWED_STATUSES = frozenset({"PASS", "NO_CHANGE", "FAIL", "TIMEOUT", "STOPPED", "BLOCKED"})
_ALLOWED_CATEGORIES = frozenset({
    "network_transient",
    "service_unavailable",
    "rate_limited",
    "test_regression",
    "timeout",
    "process_crash",
    "invalid_task",
    "invalid_evidence",
    "security_violation",
    "state_persistence_failure",
    "unknown",
})


def record_outcome(
    db_path: str | Path,
    *,
    namespace: str,
    task_id: str,
    status: str,
    category: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Persist a sanitized outcome as a searchable, idempotent RAG document."""
    if status not in _ALLOWED_STATUSES:
        raise ValueError("status is not allowlisted")
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError("category is not allowlisted")
    if not task_id or len(task_id) > 100 or not all(c.isalnum() or c in "._-" for c in task_id):
        raise ValueError("task_id is invalid")
    if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint.lower()):
        raise ValueError("fingerprint must be a SHA-256 hex digest")

    store = RagStore(db_path)
    source_id = f"{task_id}:{fingerprint.lower()}"
    title = f"Recovery outcome {status}: {category}"
    content = (
        f"task_id: {task_id}\n"
        f"status: {status}\n"
        f"category: {category}\n"
        f"fingerprint: {fingerprint.lower()}"
    )
    return store.add_document(
        namespace=namespace,
        source="recovery_ai",
        source_id=source_id,
        title=title,
        content=content,
        metadata={
            "task_id": task_id,
            "status": status,
            "category": category,
            "fingerprint": fingerprint.lower(),
        },
    )


def search_prior_outcomes(
    db_path: str | Path,
    *,
    namespace: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search saved sanitized outcomes; callers must treat matches as evidence, not commands."""
    return RagStore(db_path).search(namespace=namespace, query=query, limit=limit)
