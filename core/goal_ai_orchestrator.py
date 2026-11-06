"""Goal AI planning contract that composes bounded jobs with Chain Job AI.

Goal AI owns the outcome and dependency graph. Chain Job AI remains the
independent run-continuation verifier. This module validates plans and derives
eligible queue candidates; it never persists, executes, retries, clears HOLD,
approves, merges, or deploys jobs.
"""
from __future__ import annotations

import re
from typing import Any

_GOAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_ALLOWED_AGENTS = frozenset({"research", "development", "test", "review", "report"})
_ALLOWED_JOB_FIELDS = {
    "id", "title", "instruction", "agent", "depends_on",
    "allowed_paths", "approval_required",
}
_ALLOWED_PLAN_FIELDS = {"schema_version", "goal_id", "goal", "max_parallel_jobs", "jobs"}


class GoalPlanError(ValueError):
    """A Goal AI plan is malformed, unsafe, or internally inconsistent."""


def _safe_path(value: object) -> bool:
    if not isinstance(value, str) or not value or chr(92) in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def validate_goal_plan(payload: object) -> dict[str, Any]:
    """Validate a bounded DAG emitted by Goal AI; preserve declared job order."""
    if not isinstance(payload, dict) or set(payload) != _ALLOWED_PLAN_FIELDS:
        raise GoalPlanError("goal_plan_schema_invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise GoalPlanError("goal_plan_schema_unsupported")
    if not isinstance(payload["goal_id"], str) or not _GOAL_ID.fullmatch(payload["goal_id"]):
        raise GoalPlanError("goal_id_invalid")
    if not isinstance(payload["goal"], str) or not payload["goal"].strip() or len(payload["goal"]) > 2000:
        raise GoalPlanError("goal_text_invalid")
    parallel = payload["max_parallel_jobs"]
    if type(parallel) is not int or not 1 <= parallel <= 4:
        raise GoalPlanError("parallel_limit_invalid")
    jobs = payload["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 12:
        raise GoalPlanError("job_count_invalid")

    by_id: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict) or set(job) != _ALLOWED_JOB_FIELDS:
            raise GoalPlanError("job_schema_invalid")
        job_id = job["id"]
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id) or job_id in by_id:
            raise GoalPlanError("job_id_invalid_or_duplicate")
        if not isinstance(job["title"], str) or not job["title"].strip() or len(job["title"]) > 160:
            raise GoalPlanError("job_title_invalid")
        if not isinstance(job["instruction"], str) or not job["instruction"].strip() or len(job["instruction"]) > 3000:
            raise GoalPlanError("job_instruction_invalid")
        if not isinstance(job["agent"], str) or job["agent"] not in _ALLOWED_AGENTS:
            raise GoalPlanError("job_agent_invalid")
        if type(job["approval_required"]) is not bool:
            raise GoalPlanError("approval_flag_invalid")
        paths = job["allowed_paths"]
        if not isinstance(paths, list) or len(paths) > 40:
            raise GoalPlanError("allowed_paths_invalid")
        if any(not _safe_path(path) for path in paths) or len(set(paths)) != len(paths):
            raise GoalPlanError("allowed_paths_invalid")
        if job["agent"] == "development" and not paths:
            raise GoalPlanError("development_job_requires_path_allowlist")
        dependencies = job["depends_on"]
        if (not isinstance(dependencies, list)
                or any(not isinstance(dep, str) or not _JOB_ID.fullmatch(dep) for dep in dependencies)
                or len(dependencies) != len(set(dependencies))
                or job_id in dependencies):
            raise GoalPlanError("job_dependencies_invalid")
        by_id[job_id] = dict(job)

    for job in by_id.values():
        if any(dep not in by_id for dep in job["depends_on"]):
            raise GoalPlanError("job_dependency_unknown")

    # Kahn's algorithm: reject cycles without relying on the model's claimed order.
    pending = {job_id: set(job["depends_on"]) for job_id, job in by_id.items()}
    resolved: set[str] = set()
    while pending:
        ready = [job_id for job_id, deps in pending.items() if deps <= resolved]
        if not ready:
            raise GoalPlanError("job_dependency_cycle")
        for job_id in ready:
            resolved.add(job_id)
            del pending[job_id]

    return {
        "schema_version": 1,
        "goal_id": payload["goal_id"],
        "goal": payload["goal"].strip(),
        "max_parallel_jobs": parallel,
        "jobs": [by_id[job["id"]] for job in jobs],
    }


def evaluate_goal_progress(
    plan: object,
    *,
    completed_job_ids: object = (),
    running_job_ids: object = (),
    failed_job_ids: object = (),
    blocked_job_ids: object = (),
    approved_job_ids: object = (),
) -> dict[str, Any]:
    """Return bounded next-job candidates from a validated plan and durable states."""
    validated = validate_goal_plan(plan)
    groups = {
        "completed": completed_job_ids,
        "running": running_job_ids,
        "failed": failed_job_ids,
        "blocked": blocked_job_ids,
        "approved": approved_job_ids,
    }
    normalized: dict[str, set[str]] = {}
    known = {job["id"] for job in validated["jobs"]}
    for name, values in groups.items():
        if not isinstance(values, (list, tuple, set, frozenset)):
            raise GoalPlanError(f"{name}_job_ids_invalid")
        if any(not isinstance(item, str) or item not in known for item in values):
            raise GoalPlanError(f"{name}_job_id_unknown")
        if len(values) != len(set(values)):
            raise GoalPlanError(f"{name}_job_ids_duplicate")
        normalized[name] = set(values)

    by_id = {job["id"]: job for job in validated["jobs"]}
    names = ("completed", "running", "failed", "blocked")
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            if normalized[left] & normalized[right]:
                raise GoalPlanError("job_states_overlap")
    if any(not by_id.get(job_id, {}).get("approval_required") for job_id in normalized["approved"]):
        raise GoalPlanError("approval_for_unprotected_job")

    completed = normalized["completed"]
    running = normalized["running"]
    failed = normalized["failed"]
    blocked = normalized["blocked"]

    for job_id in completed | running:
        if not set(by_id[job_id]["depends_on"]) <= completed:
            raise GoalPlanError("job_state_dependency_not_satisfied")

    base = {
        "schema_version": 1,
        "goal_id": validated["goal_id"],
        "completed_count": len(completed),
        "running_count": len(running),
        "remaining_count": len(known - completed),
        "execution_authorized": False,
        "merge_authorized": False,
        "deploy_authorized": False,
    }
    if failed or blocked:
        return {
            **base, "status": "HOLD", "ready_job_ids": [],
            "reason": "failed_or_blocked_job_requires_recovery_review",
        }
    if completed == known:
        return {**base, "status": "COMPLETE", "ready_job_ids": [], "reason": "all_goal_jobs_verified_complete"}

    slots = max(0, validated["max_parallel_jobs"] - len(running))
    dependency_ready = [
        job for job in validated["jobs"]
        if job["id"] not in completed | running
        and set(job["depends_on"]) <= completed
    ]
    approval_pending = [
        job["id"] for job in dependency_ready
        if job["approval_required"] and job["id"] not in normalized["approved"]
    ]
    ready = [
        job["id"] for job in dependency_ready
        if not job["approval_required"] or job["id"] in normalized["approved"]
    ][:slots]
    if ready:
        return {
            **base, "status": "READY", "ready_job_ids": ready,
            "approval_pending_job_ids": approval_pending,
            "reason": "dependencies_and_required_approvals_verified",
        }
    if approval_pending:
        return {
            **base, "status": "APPROVAL_REQUIRED", "ready_job_ids": [],
            "approval_pending_job_ids": approval_pending,
            "reason": "human_approval_required_before_enqueue",
        }
    if running:
        return {**base, "status": "RUNNING", "ready_job_ids": [], "approval_pending_job_ids": [], "reason": "waiting_for_running_jobs"}
    return {**base, "status": "HOLD", "ready_job_ids": [], "approval_pending_job_ids": [], "reason": "no_runnable_job_or_state_inconsistency"}


__all__ = ["GoalPlanError", "evaluate_goal_progress", "validate_goal_plan"]
