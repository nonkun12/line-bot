"""Adapters connecting Goal AI proposals to durable JOBs and typed execution."""
from __future__ import annotations

from typing import Any

import job_store


def normalize_job_status(status: object) -> str:
    """Normalize the two existing successful terminal spellings."""
    if status in {"done", "completed"}:
        return "done"
    if status in {"pending", "running", "failed", "held"}:
        return status
    return "unknown"


def load_goal_job_states(goal_id: str) -> dict[str, str]:
    """Build planner state keyed by stable logical JOB key."""
    return {
        item["job_key"]: normalize_job_status(item["status"])
        for item in job_store.list_goal_child_jobs(goal_id)
    }


def persist_next_job(
    plan: object,
    *,
    user_id: str,
    parent_job_id: int | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Persist one already-authorized planner proposal with idempotent identity."""
    if not isinstance(plan, dict) or plan.get("decision") != "PROPOSE_CHILD_JOB":
        raise ValueError("plan is not a child JOB proposal")
    policy = plan.get("autonomy_policy")
    permissions = plan.get("permissions")
    job = plan.get("job")
    if (
        plan.get("human_approval_required") is not False
        or not isinstance(policy, dict)
        or policy.get("decision") != "AUTO_APPROVE"
        or not isinstance(permissions, dict)
        or permissions.get("merge") is not False
        or permissions.get("deploy") is not False
        or not isinstance(job, dict)
    ):
        raise ValueError("proposal does not contain trusted bounded-autonomy evidence")

    goal_id = plan.get("goal_id")
    job_key = job.get("id")
    criterion_id = plan.get("criterion_id")
    dependencies = job.get("depends_on", [])
    if (
        not isinstance(goal_id, str) or not goal_id.strip()
        or not isinstance(job_key, str) or not job_key.strip()
        or not isinstance(criterion_id, str) or not criterion_id.strip()
        or not isinstance(dependencies, list)
        or any(not isinstance(dep, str) or not dep.strip() for dep in dependencies)
    ):
        raise ValueError("proposal identity or dependencies are invalid")
    if dependencies and parent_job_id is None:
        raise ValueError("a dependent child JOB requires its completed parent JOB id")

    payload = {
        "schema_version": 1,
        "goal_id": goal_id,
        "job_key": job_key,
        "criterion_id": criterion_id,
        "stage": job.get("stage"),
        "instruction": job.get("instruction"),
        "allowed_paths": job.get("allowed_paths"),
        "depends_on": dependencies,
        "autonomy_grant_id": plan.get("autonomy_grant_id"),
        "autonomy_policy": policy,
    }
    job_id, created = job_store.create_goal_child_job(
        user_id, goal_id, job_key, criterion_id, payload,
        parent_job_id=parent_job_id, max_retries=max_retries,
    )
    return {
        "goal_id": goal_id,
        "job_key": job_key,
        "job_id": job_id,
        "status": "pending",
        "created": created,
        "idempotent_replay": not created,
    }


__all__ = ["normalize_job_status", "load_goal_job_states", "persist_next_job"]
