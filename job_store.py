"""Compatibility wrapper for asynchronous Job storage.

Keeps the Worker API compatible with the current main db.py schema.
"""

import db


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    return db.create_job(user_id=user_id, message=message, job_type=job_type,
                         source=source, parent_job_id=parent_job_id,
                         max_retries=max_retries)


def get_job(job_id):
    return db.get_job(job_id)


def claim_pending_job():
    return db.claim_pending_job()


def update_job(job_id, status=None, result=None, last_error=None,
               retry_count=None, claimed_at=None, clear_claimed_at=False):
    # main's db.py uses updated_at as the lease clock and has no claimed_at column.
    return db.update_job(job_id, status=status, result=result,
                         last_error=last_error, retry_count=retry_count)


def save_checkpoint(job_id, step_name, step_status, output_snapshot=None):
    return db.save_checkpoint(job_id, step_name, step_status, output_snapshot)


def get_latest_checkpoint(job_id):
    return db.get_latest_checkpoint(job_id)
