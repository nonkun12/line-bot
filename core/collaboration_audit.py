"""Bounded SQLite audit storage for request-scoped agent collaboration."""
from __future__ import annotations

import json
from typing import Any

from db import get_conn

_MAX_SNAPSHOT_BYTES = 16_384
_MAX_ROWS_PER_USER = 20


def record_collaboration_snapshot(*, user_id: str, snapshot: dict[str, Any]) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be an object")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
        raise ValueError("collaboration snapshot exceeds size limit")
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS management_collaboration_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO management_collaboration_snapshots(user_id, snapshot_json)
            VALUES (?, ?)
        """, (user_id.strip(), payload))
        conn.execute("""
            DELETE FROM management_collaboration_snapshots
            WHERE user_id=? AND id NOT IN (
                SELECT id FROM management_collaboration_snapshots
                WHERE user_id=? ORDER BY id DESC LIMIT ?
            )
        """, (user_id.strip(), user_id.strip(), _MAX_ROWS_PER_USER))


def list_collaboration_snapshots(*, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT snapshot_json, created_at
            FROM management_collaboration_snapshots
            WHERE user_id=?
            ORDER BY id DESC LIMIT ?
        """, (user_id.strip(), limit)).fetchall()
    result = []
    for payload, created_at in rows:
        value = json.loads(payload)
        if isinstance(value, dict):
            result.append({"created_at": created_at, "snapshot": value})
    return result


__all__ = ["record_collaboration_snapshot", "list_collaboration_snapshots"]
