"""Adapters connecting Goal AI proposals to durable JOBs and typed execution."""
from __future__ import annotations

import json
from typing import Any

import job_store
from scripts.goal_job_chain import plan_next_job


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


def _persist_next_job(
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




def derive_goal_criterion_results(
    goal: dict[str, Any],
    initial_results: dict[str, str] | None = None,
) -> dict[str, str]:
    """Derive criteria from persisted child outcomes; never infer PASS from status alone."""
    initial_results = initial_results or {}
    records = {
        item["job_key"]: item
        for item in job_store.list_goal_child_jobs(goal["goal_id"])
    }
    derived: dict[str, str] = {}
    for criterion in goal["success_criteria"]:
        criterion_id = criterion["id"]
        definitions = [
            item for item in goal["jobs"]
            if item.get("criterion_id") == criterion_id
        ]
        if not definitions:
            derived[criterion_id] = initial_results.get(criterion_id, "UNKNOWN")
            continue

        criterion_records = [records.get(item["id"]) for item in definitions]
        present = [item for item in criterion_records if item is not None]
        if any(item["status"] == "failed" for item in present):
            derived[criterion_id] = "FAIL"
            continue
        if any(item["status"] in {"pending", "running", "held"} for item in present):
            derived[criterion_id] = "UNKNOWN"
            continue
        if len(present) != len(definitions):
            derived[criterion_id] = "FAIL"
            continue

        all_pass = True
        for record in present:
            if normalize_job_status(record["status"]) != "done":
                all_pass = False
                break
            try:
                result = json.loads(record["result"] or "")
            except (TypeError, ValueError):
                all_pass = False
                break
            if not isinstance(result, dict) or result.get("outcome") != "PASS" or not result.get("evidence"):
                all_pass = False
                break
        derived[criterion_id] = "PASS" if all_pass else "FAIL"
    return derived


def advance_goal(
    goal: object,
    *,
    user_id: str,
    autonomy_grant: object,
    initial_criterion_results: dict[str, str] | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Plan, persist at most one next child, and stop only on verified Goal completion."""
    if not isinstance(goal, dict) or not isinstance(goal.get("goal_id"), str):
        raise ValueError("goal contract is invalid")
    records = job_store.list_goal_child_jobs(goal["goal_id"])
    states = {item["job_key"]: normalize_job_status(item["status"]) for item in records}
    criteria = derive_goal_criterion_results(goal, initial_criterion_results)
    plan = plan_next_job(
        goal, criteria, states, autonomy_grant=autonomy_grant
    )
    if plan.get("decision") != "PROPOSE_CHILD_JOB":
        return {"plan": plan, "persisted_job": None, "criterion_results": criteria}

    selected = plan["job"]
    dependencies = selected.get("depends_on", [])
    parent_id = None
    if dependencies:
        by_key = {item["job_key"]: item for item in records}
        missing = [key for key in dependencies if key not in by_key]
        if missing:
            raise ValueError("completed dependency record is missing")
        if any(normalize_job_status(by_key[key]["status"]) != "done" for key in dependencies):
            raise ValueError("all parent JOB dependencies must be completed")
        parent_id = by_key[dependencies[-1]]["job_id"]

    persisted = _persist_next_job(
        plan, user_id=user_id, parent_job_id=parent_id, max_retries=max_retries
    )
    return {
        "plan": plan,
        "persisted_job": persisted,
        "criterion_results": criteria,
    }


__all__ = ["normalize_job_status", "load_goal_job_states", "derive_goal_criterion_results", "advance_goal"]
