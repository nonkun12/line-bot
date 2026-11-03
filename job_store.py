"""Small persistence wrapper for asynchronous AI jobs.

The database schema remains owned by db.py; this module keeps Job callers
independent from SQL details so the storage can later move to Postgres.
"""

import db


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    return db.create_job(
        user_id=user_id,
        message=message,
        job_type=job_type,
        source=source,
        parent_job_id=parent_job_id,
        max_retries=max_retries,
    )


def get_job(job_id):
    return db.get_job(job_id)


def claim_pending_job():
    return db.claim_pending_job()


def update_job(job_id, status=None, result=None, last_error=None, retry_count=None):
    return db.update_job(
        job_id,
        status=status,
        result=result,
        last_error=last_error,
        retry_count=retry_count,
    )


def save_checkpoint(job_id, step_name, step_status, output_snapshot=None):
    return db.save_checkpoint(job_id, step_name, step_status, output_snapshot)


def get_latest_checkpoint(job_id):
    return db.get_latest_checkpoint(job_id)


def create_goal_child_job(
    user_id, goal_id, job_key, criterion_id, payload, *,
    parent_job_id=None, max_retries=2,
):
    return db.create_goal_child_job(
        user_id, goal_id, job_key, criterion_id, payload,
        parent_job_id=parent_job_id, max_retries=max_retries,
    )


def list_goal_child_jobs(goal_id):
    return db.list_goal_child_jobs(goal_id)


def claim_pending_job_by_type(job_type, *, stale_after_seconds=900):
    return db.claim_pending_job_by_type(
        job_type, stale_after_seconds=stale_after_seconds
    )


def complete_claimed_job(
    job_id, claim_token, *, success, result=None, last_error=None,
):
    return db.complete_claimed_job(
        job_id, claim_token, success=success, result=result, last_error=last_error
    )
