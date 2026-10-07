"""Durable pending queue for work that must wait for a Mac-side worker.

The queue is intentionally transport-agnostic: LINE/cloud code can enqueue work,
while a Mac-local worker (for example Hermes Kanban) claims and executes it.
No task is considered complete merely because an executor reports success; the
worker must explicitly record a terminal result after its own verification.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_STATES = frozenset({"PASS", "FAILED", "BLOCKED"})
ACTIVE_STATES = frozenset({"PENDING", "RUNNING"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueueTask:
    task_id: str
    request: str
    source: str
    priority: int
    status: str
    retry_count: int
    approval_required: bool
    approved: bool
    result: str | None
    sha: str | None
    error: str | None
    created_at: str
    updated_at: str


class PendingQueue:
    """SQLite-backed durable queue with atomic claiming."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_tasks (
                    task_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    source TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK (
                        status IN ('PENDING', 'RUNNING', 'PASS', 'FAILED', 'BLOCKED')
                    ),
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    approval_required INTEGER NOT NULL DEFAULT 1,
                    approved INTEGER NOT NULL DEFAULT 0,
                    result TEXT,
                    sha TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_ready "
                "ON queue_tasks(status, approved, priority DESC, created_at)"
            )

    def enqueue(
        self,
        request: str,
        *,
        source: str = "line",
        priority: int = 0,
        approval_required: bool = True,
        approved: bool = False,
    ) -> str:
        if not request.strip():
            raise ValueError("request must not be empty")
        if approval_required and approved:
            raise ValueError("approved cannot bypass required approval at enqueue time")
        task_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO queue_tasks
                (task_id, request, source, priority, status, approval_required,
                 approved, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                """,
                (
                    task_id,
                    request,
                    source,
                    priority,
                    int(approval_required),
                    int(approved),
                    now,
                    now,
                ),
            )
        return task_id

    def approve(self, task_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE queue_tasks
                SET approved = 1, updated_at = ?
                WHERE task_id = ? AND status = 'PENDING'
                """,
                (_now(), task_id),
            )
        return cur.rowcount == 1

    def claim_next(self) -> QueueTask | None:
        """Atomically claim one approved task; never claims an unapproved task."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM queue_tasks
                WHERE status = 'PENDING'
                  AND (approval_required = 0 OR approved = 1)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            now = _now()
            cur = conn.execute(
                """
                UPDATE queue_tasks
                SET status = 'RUNNING', updated_at = ?
                WHERE task_id = ? AND status = 'PENDING'
                """,
                (now, row["task_id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT * FROM queue_tasks WHERE task_id = ?", (row["task_id"],)
            ).fetchone()
            conn.commit()
        return self._task(row)

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        result: str | None = None,
        sha: str | None = None,
        error: str | None = None,
    ) -> bool:
        if status not in TERMINAL_STATES:
            raise ValueError(f"invalid terminal status: {status}")
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE queue_tasks
                SET status = ?, result = ?, sha = ?, error = ?, updated_at = ?
                WHERE task_id = ? AND status = 'RUNNING'
                """,
                (status, result, sha, error, _now(), task_id),
            )
        return cur.rowcount == 1

    def recover_running(self, task_id: str) -> bool:
        """Return an interrupted RUNNING task to PENDING without marking success."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE queue_tasks
                SET status = 'PENDING', retry_count = retry_count + 1,
                    updated_at = ?
                WHERE task_id = ? AND status = 'RUNNING'
                """,
                (_now(), task_id),
            )
        return cur.rowcount == 1

    def get(self, task_id: str) -> QueueTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM queue_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._task(row) if row else None

    @staticmethod
    def _task(row: sqlite3.Row) -> QueueTask:
        return QueueTask(
            task_id=row["task_id"],
            request=row["request"],
            source=row["source"],
            priority=row["priority"],
            status=row["status"],
            retry_count=row["retry_count"],
            approval_required=bool(row["approval_required"]),
            approved=bool(row["approved"]),
            result=row["result"],
            sha=row["sha"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
