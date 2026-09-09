"""Compatibility wrapper for asynchronous Job storage."""

from __future__ import annotations

import json
import os

import db


REVIEW_POLL_DELAY_SECONDS = int(os.environ.get("JOB_REVIEW_POLL_DELAY_SECONDS", "30"))


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    return db.create_job(user_id=user_id, message=message, job_type=job_type,
                         source=source, parent_job_id=parent_job_id,
                         max_retries=max_retries)


def get_job(job_id):
    return db.get_job(job_id)


def claim_pending_job(worker_id=None, lease_seconds=None):
    kwargs = {}
    if worker_id is not None:
        kwargs["worker_id"] = worker_id
    if lease_seconds is not None:
        kwargs["lease_seconds"] = lease_seconds
    return db.claim_pending_job(**kwargs)


def renew_job_lease(job_id, worker_id, lease_seconds=None):
    if lease_seconds is None:
        return db.renew_job_lease(job_id, worker_id)
    return db.renew_job_lease(job_id, worker_id, lease_seconds=lease_seconds)


def update_job(job_id, status=None, result=None, last_error=None, retry_count=None,
               claimed_at=None, clear_claimed_at=False, worker_id=None,
               lease_until=None, next_run_at=None, clear_lease=False):
    return db.update_job(job_id, status=status, result=result,
                         last_error=last_error, retry_count=retry_count,
                         worker_id=worker_id, lease_until=lease_until,
                         next_run_at=next_run_at,
                         clear_lease=clear_lease or clear_claimed_at)


def _is_review_pending(result: object) -> bool:
    if isinstance(result, dict):
        review = result.get("review_result")
        return isinstance(review, dict) and review.get("status") == "pending"
    try:
        payload = json.loads(str(result or ""))
    except (TypeError, ValueError):
        return False
    review = payload.get("review_result") if isinstance(payload, dict) else None
    return isinstance(review, dict) and review.get("status") == "pending"


def update_job_owned(job_id, worker_id, status=None, result=None, last_error=None,
                     retry_count=None, next_run_at=None, clear_lease=False):
    """部分更新を、現在leaseを所有しているWorkerに限定して行う。"""
    fields = []
    values = []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if result is not None:
        fields.append("result=?")
        values.append(result)
    if last_error is not None:
        fields.append("last_error=?")
        values.append(last_error)
    if retry_count is not None:
        fields.append("retry_count=?")
        values.append(retry_count)

    if next_run_at is not None:
        fields.append("next_run_at=?")
        values.append(next_run_at)
    elif status == "pending" and _is_review_pending(result):
        fields.append("next_run_at=datetime('now', ?)")
        values.append(f"+{max(1, REVIEW_POLL_DELAY_SECONDS)} seconds")

    if clear_lease:
        fields.extend(["worker_id=NULL", "lease_until=NULL"])
    if not fields:
        return False

    fields.append("updated_at=CURRENT_TIMESTAMP")
    values.extend([job_id, str(worker_id)])
    with db.get_conn() as conn:
        db._ensure_job_columns(conn)
        cursor = conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} "
            "WHERE id=? AND status='running' AND worker_id=? "
            "AND lease_until IS NOT NULL AND julianday(lease_until) > julianday('now')",
            values,
        )
        return cursor.rowcount > 0


def save_checkpoint(job_id, step_name, step_status, output_snapshot=None):
    return db.save_checkpoint(job_id, step_name, step_status, output_snapshot)


def get_latest_checkpoint(job_id):
    return db.get_latest_checkpoint(job_id)
