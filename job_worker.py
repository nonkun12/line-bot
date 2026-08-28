"""Minimal synchronous worker for persisted AI jobs.

This first worker intentionally does not connect to n8n or the AI App Builder.
It proves the Job lifecycle and checkpoint semantics before external execution
is introduced.
"""

import job_store


STEP_NAME = "worker"


def run_once(executor=None):
    """Claim one pending job and execute it with a small injected callable.

    The executor receives the job dict and may return a string result.  If no
    executor is supplied, the worker performs a safe dry-run and records that
    execution occurred.  External AI execution is deliberately added later.
    """
    job = job_store.claim_pending_job()
    if job is None:
        return None

    job_id = job["id"]
    job_store.save_checkpoint(job_id, STEP_NAME, "started")

    try:
        result = executor(job) if executor is not None else "dry_run"
        job_store.save_checkpoint(job_id, STEP_NAME, "completed", str(result))
        job_store.update_job(job_id, status="done", result=str(result), last_error=None)
        return job_store.get_job(job_id)
    except Exception as exc:
        message = str(exc)
        job_store.save_checkpoint(job_id, STEP_NAME, "failed", message)
        job_store.update_job(job_id, status="failed", last_error=message)
        return job_store.get_job(job_id)


if __name__ == "__main__":
    result = run_once()
    print(result if result is not None else "no pending jobs")
