"""Short-lived durable context for safe LINE development continuation."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MAX_INSTRUCTION_LENGTH = 2000
_DEFAULT_TTL_HOURS = 24


def _database_path() -> str:
    return os.environ.get("CHAT_DB_PATH", str(Path(__file__).resolve().parents[1] / "chat.db"))


def save_last_instruction(user_id: str, instruction: str, request_id: str, *, now=None) -> bool:
    """Persist only an accepted development request; retain it for at most 24 hours."""
    user_id = str(user_id or "").strip()
    instruction = str(instruction or "").strip()
    request_id = str(request_id or "").strip()
    if not user_id or not instruction or len(instruction) > _MAX_INSTRUCTION_LENGTH or not request_id:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    expires = current + timedelta(hours=_DEFAULT_TTL_HOURS)
    with sqlite3.connect(_database_path(), timeout=5) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS line_development_context (
                user_id TEXT PRIMARY KEY,
                instruction TEXT NOT NULL,
                request_id TEXT NOT NULL,
                accepted_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO line_development_context
                (user_id, instruction, request_id, accepted_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                instruction=excluded.instruction,
                request_id=excluded.request_id,
                accepted_at=excluded.accepted_at,
                expires_at=excluded.expires_at
        """, (user_id, instruction, request_id, current.isoformat(), expires.isoformat()))
        conn.execute(
            "DELETE FROM line_development_context WHERE expires_at <= ?",
            (current.isoformat(),),
        )
    return True


def get_last_instruction(user_id: str, *, now=None) -> dict[str, str] | None:
    """Return the user's unexpired accepted request, without extending its TTL."""
    user_id = str(user_id or "").strip()
    if not user_id:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    with sqlite3.connect(_database_path(), timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("""
                SELECT instruction, request_id, accepted_at, expires_at
                FROM line_development_context
                WHERE user_id=? AND expires_at > ?
            """, (user_id, current.isoformat())).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
    return dict(row) if row else None
