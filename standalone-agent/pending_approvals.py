"""Job-scoped approval storage and legacy user approval helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from db import get_conn


class PendingStatus(str, Enum):
    PENDING = "pending"
    EXPIRED = "expired"
    NONE = "none"


VALID_OPERATIONS = {"commit", "deploy"}


@dataclass
class ApprovalRecord:
    user_id: str
    requested_at: str
    expires_at: str
    approved: bool = False
    rejected: bool = False


def ensure_job_approvals_table() -> None:
    """Create the Job-scoped approval table without changing legacy approvals."""
    with get_conn() as conn:
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


def _validate_operation(operation: str) -> None:
    if operation not in VALID_OPERATIONS:
        raise ValueError(f"unsupported approval operation: {operation!r}")


def request_job_approval(
    job_id: int,
    user_id: str,
    operation: str,
    expires_at: Optional[str] = None,
) -> dict:
    """Create the approval request once; repeated calls return the same record."""
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO job_approvals(job_id, user_id, operation, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id, operation) DO NOTHING
            """,
            (job_id, user_id, operation, expires_at),
        )
    return get_job_approval(job_id, operation)


def get_job_approval(job_id: int, operation: str) -> Optional[dict]:
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, job_id, user_id, operation, status,
                   requested_at, expires_at, approved_at,
                   approved_by, rejected_at, consumed_at
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


def approve_job_approval(job_id: int, operation: str, approved_by: str) -> bool:
    """Approve exactly one pending Job+operation request."""
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='approved', approved_at=CURRENT_TIMESTAMP, approved_by=?
            WHERE job_id=? AND operation=? AND status='pending'
            """,
            (approved_by, job_id, operation),
        )
        return cursor.rowcount == 1


def reject_job_approval(job_id: int, operation: str) -> bool:
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='rejected', rejected_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND operation=? AND status='pending'
            """,
            (job_id, operation),
        )
        return cursor.rowcount == 1


def expire_job_approval(job_id: int, operation: str) -> bool:
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
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


def consume_job_approval(job_id: int, operation: str) -> bool:
    """Atomically consume an approved request; prevents replay."""
    _validate_operation(operation)
    ensure_job_approvals_table()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE job_approvals
            SET status='consumed', consumed_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND operation=? AND status='approved'
            """,
            (job_id, operation),
        )
        return cursor.rowcount == 1


def get_job_approval_status(job_id: int, operation: str) -> str:
    record = get_job_approval(job_id, operation)
    if record is None:
        return "none"

    if record["status"] == "pending" and record.get("expires_at"):
        try:
            expires = datetime.fromisoformat(str(record["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                expire_job_approval(job_id, operation)
                return "expired"
        except ValueError:
            pass

    return record["status"]


# Legacy user-level approval helpers remain for existing callers.
def _fetch_latest_approval_record(user_id: str) -> Optional[ApprovalRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT user_id, requested_at, expires_at, approved, rejected
            FROM approvals
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return ApprovalRecord(
        user_id=row[0],
        requested_at=row[1],
        expires_at=row[2],
        approved=bool(row[3]),
        rejected=bool(row[4]),
    )


def _parse_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_pending_status(user_id: str, now: Optional[datetime] = None) -> PendingStatus:
    try:
        record = _fetch_latest_approval_record(user_id)
    except Exception as e:
        print("DB GET_PENDING_STATUS ERROR:", e)
        return PendingStatus.PENDING

    if record is None or not (not record.approved and not record.rejected):
        return PendingStatus.NONE

    now = now or datetime.now(timezone.utc)
    if _parse_datetime(record.expires_at) <= now:
        return PendingStatus.EXPIRED
    return PendingStatus.PENDING
