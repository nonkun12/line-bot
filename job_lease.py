"""Lease/recovery helpers for the asynchronous Job worker."""

from __future__ import annotations

import os

import db


DEFAULT_STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "1800"))


def has_active_job_lease(job_id: int, worker_id: str) -> bool:
    """Return True only when the given worker still owns a live Job lease."""
    if job_id is None or not worker_id:
        return False
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM jobs
            WHERE id=?
              AND status='running'
              AND worker_id=?
              AND lease_until IS NOT NULL
              AND julianday(lease_until) > julianday('now')
            LIMIT 1
            """,
            (int(job_id), worker_id),
        ).fetchone()
    return row is not None


def require_active_job_lease(state: dict) -> None:
    """Fail closed for asynchronous Job side effects when lease ownership is lost."""
    job_id = state.get("job_id")
    worker_id = state.get("worker_id")
    if job_id is not None and not has_active_job_lease(job_id, worker_id):
        raise RuntimeError("worker lease is no longer active; external side effect aborted")


def recover_stale_jobs(stale_seconds: int = DEFAULT_STALE_SECONDS) -> list[int]:
    """Requeue running Jobs whose explicit lease has expired.

    Legacy Jobs without lease_until still fall back to updated_at so existing
    rows can be recovered safely after this schema migration.
    """
    stale_seconds = max(1, int(stale_seconds))
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE status='running'
              AND (
                    (lease_until IS NOT NULL AND julianday(lease_until) <= julianday('now'))
                    OR
                    (lease_until IS NULL
                     AND (julianday('now') - julianday(updated_at)) * 86400 > ?)
                  )
            ORDER BY id
            """,
            (stale_seconds,),
        ).fetchall()
        job_ids = [row[0] for row in rows]
        for job_id in job_ids:
            conn.execute(
                """
                UPDATE jobs
                SET status='pending',
                    worker_id=NULL,
                    lease_until=NULL,
                    last_error='worker lease expired; job requeued',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running'
                """,
                (job_id,),
            )

    for job_id in job_ids:
        db.save_checkpoint(
            job_id,
            "worker_recovery",
            "stalled",
            "worker lease expired; requeued",
        )
    return job_ids
