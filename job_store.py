"""Small persistence wrapper for asynchronous AI jobs.

The database schema remains owned by db.py; this module keeps Job callers
independent from SQL details so the storage can later move to Postgres.
"""

import db


def create_job(user_id, message, job_type="ai_task", source="line", parent_job_id=None, max_retries=3):
    """Create a Job.

    ``source`` and ``parent_job_id`` are accepted for forward compatibility;
    the current db.py schema does not persist those fields yet.
    """
    return db.create_job(
        user_id=user_id,
        message=message,
        job_type=job_type,
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
