"""Minimal synchronous worker for persisted AI jobs.

This first worker intentionally does not connect to n8n or the AI App Builder.
It proves the Job lifecycle and checkpoint semantics before external execution
is introduced.
"""

import json

import job_store
from goal_job_runtime import normalize_job_status


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



GOAL_CHILD_JOB_TYPE = "goal_child"
GOAL_CHILD_STEP = "goal_child_executor"


def run_goal_child_once(executor=None):
    """Execute exactly one Goal child with an injected typed executor.

    There is deliberately no dry-run fallback: without a configured executor,
    no Goal child is claimed. A successful result must include explicit PASS
    or FAIL plus non-empty evidence; arbitrary strings cannot close a Goal.
    """
    if not callable(executor):
        raise ValueError("a Goal child executor is required")

    job = job_store.claim_pending_job_by_type(GOAL_CHILD_JOB_TYPE)
    if job is None:
        return None

    job_id = job["id"]
    claim_token = job.get("claim_token")
    if not isinstance(claim_token, str) or not claim_token:
        raise RuntimeError("claimed Goal child is missing its claim token")

    job_store.save_checkpoint(job_id, GOAL_CHILD_STEP, "started")
    try:
        payload = json.loads(job["message"])
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("goal_id"), str)
            or not isinstance(payload.get("job_key"), str)
            or not isinstance(payload.get("instruction"), str)
            or not isinstance(payload.get("allowed_paths"), list)
        ):
            raise ValueError("Goal child payload is invalid")

        result = executor(job, payload)
        if not isinstance(result, dict) or result.get("outcome") not in {"PASS", "FAIL"}:
            raise ValueError("executor must return outcome PASS or FAIL")
        evidence = result.get("evidence")
        if (
            not isinstance(evidence, list) or not evidence or len(evidence) > 20
            or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in evidence)
        ):
            raise ValueError("executor must return 1-20 non-empty evidence strings")
        summary = result.get("summary", "")
        if not isinstance(summary, str) or len(summary) > 2000:
            raise ValueError("executor summary is invalid")

        output = {
            "outcome": result["outcome"],
            "summary": summary,
            "evidence": evidence,
        }
        serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
        success = result["outcome"] == "PASS"
        job_store.save_checkpoint(job_id, GOAL_CHILD_STEP, "completed" if success else "failed", serialized)
        completed = job_store.complete_claimed_job(
            job_id, claim_token, success=success,
            result=serialized,
            last_error=None if success else "Goal child executor reported FAIL",
        )
        if not completed:
            raise RuntimeError("Goal child claim was lost before completion")
    except Exception as exc:
        message = str(exc)[:2000]
        job_store.save_checkpoint(job_id, GOAL_CHILD_STEP, "failed", message)
        job_store.complete_claimed_job(
            job_id, claim_token, success=False, last_error=message,
        )

    final_job = job_store.get_job(job_id)
    if final_job is not None:
        final_job["status"] = normalize_job_status(final_job["status"])
    return final_job
