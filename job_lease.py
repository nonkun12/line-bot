"""Lease/recovery helpers for the asynchronous Job worker."""

from __future__ import annotations

import os

import db


DEFAULT_STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "1800"))


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
