"""Isolated, user-scoped storage for Muse-style side conversations.

This module stores conversations only. It does not invoke agents, enqueue jobs,
or merge side-chat content into the main conversation automatically.
"""
from __future__ import annotations

import json
import re
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
MAX_CONTEXT_REFS = 20
MAX_CONTEXT_REF_LENGTH = 512
_ALLOWED_ROLES = {"user", "assistant"}
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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


def _optional_slug(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise SideChatError(f"{field} is invalid")
    return value


def _context_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > MAX_CONTEXT_REFS:
        raise SideChatError("context_refs must be a bounded list")
    refs: list[str] = []
    for item in value:
        ref = _required_text(item, "context_ref", MAX_CONTEXT_REF_LENGTH)
        if ref not in refs:
            refs.append(ref)
    return refs


def _chat_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    try:
        result["context_refs"] = json.loads(result.get("context_refs_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        result["context_refs"] = []
    return result


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
            # Backward-compatible migration for databases created before project scoping.
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(side_chats)").fetchall()
            }
            migrations = {
                "project_id": "ALTER TABLE side_chats ADD COLUMN project_id TEXT",
                "workspace_id": "ALTER TABLE side_chats ADD COLUMN workspace_id TEXT",
                "context_refs_json": (
                    "ALTER TABLE side_chats ADD COLUMN context_refs_json TEXT NOT NULL DEFAULT '[]'"
                ),
            }
            for column, statement in migrations.items():
                if column not in columns:
                    conn.execute(statement)

    def create(
        self,
        user_id: str,
        title: str,
        purpose: str = "",
        *,
        project_id: str | None = None,
        workspace_id: str | None = None,
        context_refs: list[str] | None = None,
    ) -> dict:
        user_id = _required_text(user_id, "user_id", 128)
        title = _required_text(title, "title", MAX_TITLE_LENGTH)
        if not isinstance(purpose, str) or len(purpose) > MAX_PURPOSE_LENGTH:
            raise SideChatError("purpose is invalid or too long")
        project_id = _optional_slug(project_id, "project_id")
        workspace_id = _optional_slug(workspace_id, "workspace_id")
        refs = _context_refs(context_refs)
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
                "INSERT INTO side_chats("
                "id, user_id, title, purpose, project_id, workspace_id, context_refs_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    side_chat_id, user_id, title, purpose.strip(), project_id,
                    workspace_id, json.dumps(refs, ensure_ascii=False),
                ),
            )
            row = conn.execute(
                "SELECT * FROM side_chats WHERE id=?", (side_chat_id,)
            ).fetchone()
        return _chat_dict(row)

    def list_for_user(self, user_id: str) -> list[dict]:
        user_id = _required_text(user_id, "user_id", 128)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM side_chats WHERE user_id=? ORDER BY updated_at DESC, id",
                (user_id,),
            ).fetchall()
        return [_chat_dict(row) for row in rows]

    def list_for_project(self, user_id: str, project_id: str) -> list[dict]:
        """List only the requesting user's side chats for one project."""
        user_id = _required_text(user_id, "user_id", 128)
        project_id = _required_text(project_id, "project_id", 64)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM side_chats WHERE user_id=? AND project_id=? "
                "ORDER BY updated_at DESC, id",
                (user_id, project_id),
            ).fetchall()
        return [_chat_dict(row) for row in rows]

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
        result = _chat_dict(chat)
        result["messages"] = [dict(row) for row in messages]
        return result

    def archive(self, user_id: str, side_chat_id: str) -> dict:
        """Archive an owned side chat so it no longer occupies an active slot."""
        user_id = _required_text(user_id, "user_id", 128)
        side_chat_id = _required_text(side_chat_id, "side_chat_id", 64)
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE side_chats SET status='archived', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND user_id=? AND status='active'",
                (side_chat_id, user_id),
            )
            if cursor.rowcount != 1:
                raise SideChatNotFound("active side chat not found")
            row = conn.execute(
                "SELECT * FROM side_chats WHERE id=?", (side_chat_id,)
            ).fetchone()
        return _chat_dict(row)

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
