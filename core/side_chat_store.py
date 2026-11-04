"""Isolated, user-scoped storage for Muse-style side conversations.

This module stores conversations only. It does not invoke agents, enqueue jobs,
or merge side-chat content into the main conversation automatically.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MAX_ACTIVE_SIDE_CHATS = 2
MAX_TITLE_LENGTH = 120
MAX_PURPOSE_LENGTH = 1000
MAX_MESSAGE_LENGTH = 12000
MAX_HANDOFF_LENGTH = 8000
_ALLOWED_ROLES = {"user", "assistant"}


class SideChatError(ValueError):
    """Base error for invalid or inaccessible side-chat operations."""


class SideChatNotFound(SideChatError):
    """Raised when a side chat does not exist for the requesting user."""


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SideChatError(f"{field} is required")
    value = value.strip()
    if len(value) > limit:
        raise SideChatError(f"{field} exceeds the maximum length")
    return value


class SideChatStore:
    """SQLite-backed side-chat store with strict user ownership checks."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS side_chats (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_side_chats_user_status_updated
                    ON side_chats(user_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS side_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    side_chat_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(side_chat_id) REFERENCES side_chats(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_side_chat_messages_chat_id
                    ON side_chat_messages(side_chat_id, id);
                CREATE TABLE IF NOT EXISTS side_chat_handoffs (
                    id TEXT PRIMARY KEY,
                    side_chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'dismissed')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(side_chat_id) REFERENCES side_chats(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_side_chat_handoffs_user_status
                    ON side_chat_handoffs(user_id, status, created_at DESC);
                """
            )

    def create(self, user_id: str, title: str, purpose: str = "") -> dict:
        user_id = _required_text(user_id, "user_id", 128)
        title = _required_text(title, "title", MAX_TITLE_LENGTH)
        if not isinstance(purpose, str) or len(purpose) > MAX_PURPOSE_LENGTH:
            raise SideChatError("purpose is invalid or too long")
        side_chat_id = uuid.uuid4().hex
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT COUNT(*) FROM side_chats WHERE user_id=? AND status='active'",
                (user_id,),
            ).fetchone()[0]
            if active >= MAX_ACTIVE_SIDE_CHATS:
                raise SideChatError("maximum active side chats reached")
            conn.execute(
                "INSERT INTO side_chats(id, user_id, title, purpose) VALUES (?, ?, ?, ?)",
                (side_chat_id, user_id, title, purpose.strip()),
            )
            row = conn.execute(
                "SELECT * FROM side_chats WHERE id=?", (side_chat_id,)
            ).fetchone()
        return dict(row)

    def list_for_user(self, user_id: str) -> list[dict]:
        user_id = _required_text(user_id, "user_id", 128)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM side_chats WHERE user_id=? ORDER BY updated_at DESC, id",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, user_id: str, side_chat_id: str) -> dict:
        user_id = _required_text(user_id, "user_id", 128)
        side_chat_id = _required_text(side_chat_id, "side_chat_id", 64)
        with self._session() as conn:
            chat = conn.execute(
                "SELECT * FROM side_chats WHERE id=? AND user_id=?",
                (side_chat_id, user_id),
            ).fetchone()
            if chat is None:
                raise SideChatNotFound("side chat not found")
            messages = conn.execute(
                "SELECT id, role, content, created_at FROM side_chat_messages "
                "WHERE side_chat_id=? ORDER BY id",
                (side_chat_id,),
            ).fetchall()
        result = dict(chat)
        result["messages"] = [dict(row) for row in messages]
        return result

    def append_message(
        self, user_id: str, side_chat_id: str, role: str, content: str
    ) -> dict:
        user_id = _required_text(user_id, "user_id", 128)
        side_chat_id = _required_text(side_chat_id, "side_chat_id", 64)
        if role not in _ALLOWED_ROLES:
            raise SideChatError("role must be user or assistant")
        content = _required_text(content, "content", MAX_MESSAGE_LENGTH)
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owned = conn.execute(
                "SELECT 1 FROM side_chats WHERE id=? AND user_id=? AND status='active'",
                (side_chat_id, user_id),
            ).fetchone()
            if owned is None:
                raise SideChatNotFound("active side chat not found")
            cursor = conn.execute(
                "INSERT INTO side_chat_messages(side_chat_id, role, content) VALUES (?, ?, ?)",
                (side_chat_id, role, content),
            )
            conn.execute(
                "UPDATE side_chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (side_chat_id,),
            )
            row = conn.execute(
                "SELECT id, role, content, created_at FROM side_chat_messages WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row)

    def create_handoff(self, user_id: str, side_chat_id: str, summary: str) -> dict:
        """Create a pending summary; never writes to the main chat automatically."""
        user_id = _required_text(user_id, "user_id", 128)
        side_chat_id = _required_text(side_chat_id, "side_chat_id", 64)
        summary = _required_text(summary, "summary", MAX_HANDOFF_LENGTH)
        handoff_id = uuid.uuid4().hex
        with self._session() as conn:
            owned = conn.execute(
                "SELECT 1 FROM side_chats WHERE id=? AND user_id=? AND status='active'",
                (side_chat_id, user_id),
            ).fetchone()
            if owned is None:
                raise SideChatNotFound("active side chat not found")
            conn.execute(
                "INSERT INTO side_chat_handoffs(id, side_chat_id, user_id, summary) "
                "VALUES (?, ?, ?, ?)",
                (handoff_id, side_chat_id, user_id, summary),
            )
            row = conn.execute(
                "SELECT * FROM side_chat_handoffs WHERE id=?", (handoff_id,)
            ).fetchone()
        return dict(row)

    def set_handoff_status(self, user_id: str, handoff_id: str, status: str) -> dict:
        user_id = _required_text(user_id, "user_id", 128)
        handoff_id = _required_text(handoff_id, "handoff_id", 64)
        if status not in {"accepted", "dismissed"}:
            raise SideChatError("handoff status must be accepted or dismissed")
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE side_chat_handoffs SET status=? WHERE id=? AND user_id=? "
                "AND status='pending'",
                (status, handoff_id, user_id),
            )
            if cursor.rowcount != 1:
                raise SideChatNotFound("pending handoff not found")
            row = conn.execute(
                "SELECT * FROM side_chat_handoffs WHERE id=?", (handoff_id,)
            ).fetchone()
        return dict(row)
