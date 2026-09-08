"""Small lease/recovery helpers for the SQLite-backed Job worker."""

from __future__ import annotations

import os

import db


DEFAULT_STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "1800"))


def recover_stale_jobs(stale_seconds: int = DEFAULT_STALE_SECONDS) -> list[int]:
    """Move old running Jobs back to pending using updated_at as the lease clock."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE status='running'
              AND (julianday('now') - julianday(updated_at)) * 86400 > ?
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
