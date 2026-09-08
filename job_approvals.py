"""Job-scoped approval ledger used by the asynchronous Worker."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import db


VALID_OPERATIONS = {"commit", "deploy"}
VALID_STATUSES = {"pending", "approved", "rejected", "expired", "consumed"}


def _validate_operation(operation: str) -> None:
    if operation not in VALID_OPERATIONS:
        raise ValueError(f"unsupported approval operation: {operation!r}")


def ensure_table() -> None:
    with db.get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_approvals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                approved_at TIMESTAMP,
                approved_by TEXT,
                rejected_at TIMESTAMP,
                consumed_at TIMESTAMP,
                UNIQUE(job_id, operation),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_job_approvals_job_operation
            ON job_approvals(job_id, operation)
            """
        )


def request(job_id: int, user_id: str, operation: str, expires_at: Optional[str] = None) -> dict:
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO job_approvals(job_id, user_id, operation, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id, operation) DO NOTHING
            """,
            (job_id, user_id, operation, expires_at),
        )
    return get(job_id, operation)


def get(job_id: int, operation: str) -> Optional[dict]:
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, job_id, user_id, operation, status,
                   requested_at, expires_at, approved_at, approved_by,
                   rejected_at, consumed_at
            FROM job_approvals
            WHERE job_id=? AND operation=?
            LIMIT 1
            """,
            (job_id, operation),
        ).fetchone()
    if row is None:
        return None
    keys = (
        "id", "job_id", "user_id", "operation", "status",
        "requested_at", "expires_at", "approved_at", "approved_by",
        "rejected_at", "consumed_at",
    )
    return dict(zip(keys, row))


def status(job_id: int, operation: str) -> str:
    record = get(job_id, operation)
    if record is None:
        return "none"
    if record["status"] == "pending" and record.get("expires_at"):
        try:
            expires = datetime.fromisoformat(str(record["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                expire(job_id, operation)
                return "expired"
        except ValueError:
            pass
    return record["status"]


def approve(job_id: int, operation: str, approved_by: str) -> bool:
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='approved', approved_at=CURRENT_TIMESTAMP, approved_by=?
            WHERE job_id=? AND operation=? AND status='pending'
            """,
            (approved_by, job_id, operation),
        )
        return cursor.rowcount == 1


def reject(job_id: int, operation: str) -> bool:
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='rejected', rejected_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND operation=? AND status='pending'
            """,
            (job_id, operation),
        )
        return cursor.rowcount == 1


def expire(job_id: int, operation: str) -> bool:
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='expired'
            WHERE job_id=? AND operation=? AND status='pending'
              AND expires_at IS NOT NULL
              AND julianday(expires_at) <= julianday('now')
            """,
            (job_id, operation),
        )
        return cursor.rowcount == 1


def consume(job_id: int, operation: str) -> bool:
    """Atomically consume one approval so it cannot be replayed."""
    _validate_operation(operation)
    ensure_table()
    with db.get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='consumed', consumed_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND operation=? AND status='approved'
            """,
            (job_id, operation),
        )
        return cursor.rowcount == 1
