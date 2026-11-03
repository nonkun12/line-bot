"""Typed executor for Goal AI child JOBs.

Unlike the legacy generic worker, this worker never dry-runs. A real executor
must be injected and return explicit, inspectable evidence before success is
recorded. The generic worker is separately prevented from claiming goal_child.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import goal_job_store
import job_store
import db

STEP_NAME = "goal_child_executor"


def run_once(executor: Callable[[dict[str, Any], dict[str, Any]], object] | None = None, *, job_id: int | None = None):
    """Claim and execute one Goal child. No executor means no claim and no work."""
    if executor is None:
        return None
    job = db.claim_goal_child_job(job_id) if job_id is not None else db.claim_pending_job_by_type("goal_child")
    if job is None:
        return None

    job_id = job["id"]
    claim_token = job.get("claim_token")
    job_store.save_checkpoint(job_id, STEP_NAME, "started")
    try:
        payload = goal_job_store.authorize_claimed_job(job)
        output = executor(job, payload)
        if not isinstance(output, dict):
            raise ValueError("Goal executor must return a result/evidence object")
        result = output.get("result")
        evidence = output.get("evidence")
        if not isinstance(result, str) or not result.strip() or len(result) > 20000:
            raise ValueError("Goal executor result must be a non-empty string up to 20000 characters")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
            raise ValueError("Goal executor must return non-empty evidence checks")
        serialized = json.dumps(
            {"result": result, "evidence": evidence},
            ensure_ascii=False,
            sort_keys=True,
        )
        completed = goal_job_store.complete_claimed_child_job(
            job_id,
            claim_token,
            success=True,
            result=serialized,
            evidence=evidence,
        )
        if not completed:
            raise RuntimeError("Goal child claim was lost before completion")
        job_store.save_checkpoint(job_id, STEP_NAME, "completed", serialized[:20000])
    except Exception as exc:
        message = f"{type(exc).__name__}: {str(exc)}"[:2000]
        goal_job_store.complete_claimed_child_job(
            job_id,
            claim_token,
            success=False,
            last_error=message,
        )
        job_store.save_checkpoint(job_id, STEP_NAME, "failed", message)
    return job_store.get_job(job_id)


__all__ = ["run_once"]
