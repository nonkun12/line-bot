"""Deterministic, bounded follow-up JOB generation for approved Goals.

This fallback creates documentation-only planning/recovery work. It never
widens a grant or invents code-execution permissions.
"""
from __future__ import annotations

from typing import Any


def generate_bounded_followup_job(
    record: dict[str, Any],
    criterion_results: dict[str, str],
    job_states: dict[str, str],
) -> dict[str, Any] | None:
    if not isinstance(record, dict) or not isinstance(criterion_results, dict) or not isinstance(job_states, dict):
        return None
    goal = record.get("goal")
    grant = record.get("autonomy_grant")
    if not isinstance(goal, dict) or not isinstance(grant, dict):
        return None
    if grant.get("active") is not True:
        return None
    roots = grant.get("allowed_path_prefixes")
    stages = grant.get("allowed_stages")
    if not isinstance(roots, list) or "docs/" not in roots or not isinstance(stages, list) or "design" not in stages:
        return None
    jobs = goal.get("jobs")
    criteria = goal.get("success_criteria")
    if not isinstance(jobs, list) or not isinstance(criteria, list):
        return None

    definitions_by_criterion: dict[str, list[dict[str, Any]]] = {}
    for definition in jobs:
        if isinstance(definition, dict) and isinstance(definition.get("criterion_id"), str):
            definitions_by_criterion.setdefault(definition["criterion_id"], []).append(definition)

    unmet = [
        criterion for criterion in criteria
        if isinstance(criterion, dict)
        and criterion_results.get(criterion.get("id")) == "FAIL"
    ]
    for criterion in unmet:
        criterion_id = criterion.get("id")
        definitions = definitions_by_criterion.get(criterion_id, [])
        # Do not create speculative work while any declared child can still run.
        if any(job_states.get(item.get("id")) in {"pending", "running"} for item in definitions):
            continue
        sequence = len(jobs) + 1
        job_id = f"goal-followup-{sequence:03d}"
        path = f"docs/goal-plans/{goal.get('goal_id')}/followup-{sequence:03d}.md"
        description = str(criterion.get("description", "")).strip()[:500]
        previous = ", ".join(
            f"{item.get('id')}={job_states.get(item.get('id'), 'not_registered')}"
            for item in definitions
        ) or "no prior child JOB"
        return {
            "id": job_id,
            "criterion_id": criterion_id,
            "stage": "design",
            "instruction": (
                f"Create a bounded follow-up plan at {path}. Goal: {str(goal.get('objective', ''))[:500]}. "
                f"Unmet success criterion: {description}. Previous JOB state: {previous}. "
                "Identify the missing evidence, propose the smallest safe next Sprint, define "
                "acceptance checks, and list dependencies and free-only tools. This task writes "
                "only this documentation file; do not modify application code or external systems."
            ),
            "allowed_paths": [path],
            "depends_on": [],
        }
    return None


__all__ = ["generate_bounded_followup_job"]
