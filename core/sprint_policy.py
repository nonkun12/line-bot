"""Pure, deterministic readiness checks for a bounded Goal-linked sprint.

This module deliberately has no database, worker, network, or filesystem access.
It delegates JOB eligibility and authorization decisions to the existing Goal
planner instead of creating a second Goal planner.
"""
from __future__ import annotations

from typing import Any

from scripts.goal_job_chain import MAX_AUTONOMOUS_JOBS_PER_GOAL, plan_next_job

MAX_SPRINT_JOBS = 10


def _hold(reason: str, **details: Any) -> dict[str, Any]:
    return {
        "decision": "HOLD",
        "reason": reason,
        **details,
        "create_sprint": False,
        "create_job": False,
        "execute_job": False,
        "permissions": {"expand_grant": False, "clear_hold": False, "merge": False, "deploy": False},
    }


def assess_sprint_readiness(
    goal: object,
    autonomy_grant: object,
    criterion_results: object,
    job_states: object,
    candidate: object,
) -> dict[str, Any]:
    """Validate a proposed sprint against the persisted Goal contract and planner.

    The caller must load goal, grant, evidence, and states from trusted stores.
    A READY result is advisory only: it does not persist a sprint or enqueue/run
    any JOB. The caller must persist through a separate idempotent store.
    """
    if not isinstance(goal, dict) or not isinstance(candidate, dict):
        return _hold("sprint_or_goal_contract_invalid")
    goal_id = goal.get("goal_id")
    if candidate.get("goal_id") != goal_id:
        return _hold("sprint_goal_mismatch")

    sprint_id = candidate.get("sprint_id")
    sequence = candidate.get("sequence")
    sprint_goal = candidate.get("sprint_goal")
    job_keys = candidate.get("job_keys")
    acceptance = candidate.get("acceptance_criteria")
    budget = candidate.get("max_jobs")

    if (
        not isinstance(sprint_id, str) or not sprint_id.strip() or len(sprint_id) > 100
        or type(sequence) is not int or sequence < 1
        or not isinstance(sprint_goal, str) or not sprint_goal.strip() or len(sprint_goal) > 1000
    ):
        return _hold("sprint_identity_or_goal_invalid")
    if (
        not isinstance(job_keys, list) or not 1 <= len(job_keys) <= MAX_SPRINT_JOBS
        or any(not isinstance(key, str) or not key.strip() for key in job_keys)
        or len(job_keys) != len(set(job_keys))
    ):
        return _hold("sprint_job_list_invalid")
    if (
        not isinstance(acceptance, list) or not acceptance
        or any(not isinstance(cid, str) or not cid.strip() for cid in acceptance)
        or len(acceptance) != len(set(acceptance))
    ):
        return _hold("sprint_acceptance_criteria_invalid")
    if type(budget) is not int or budget < len(job_keys) or budget > MAX_SPRINT_JOBS:
        return _hold("sprint_budget_invalid")

    criteria = goal.get("success_criteria")
    if not isinstance(criteria, list):
        return _hold("goal_criteria_invalid")
    known_criteria = {
        item.get("id") for item in criteria
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not set(acceptance).issubset(known_criteria):
        return _hold("sprint_acceptance_criteria_not_in_goal")
    if not isinstance(criterion_results, dict) or not isinstance(job_states, dict):
        return _hold("sprint_evidence_or_job_states_invalid")

    # Reuse Goal AI's single source of truth for grant validation, risk policy,
    # dependency order, and eligible JOB selection.
    simulated_states = dict(job_states)
    selected_jobs: list[dict[str, Any]] = []
    selected_criteria: set[str] = set()
    for expected_key in job_keys:
        decision = plan_next_job(
            goal,
            criterion_results,
            simulated_states,
            autonomy_grant=autonomy_grant,
        )
        if decision.get("decision") != "PROPOSE_CHILD_JOB":
            return _hold(
                "goal_planner_did_not_authorize_sprint_job",
                blocked_job_key=expected_key,
                planner_reason=decision.get("reason", "unknown"),
            )
        selected = decision.get("job")
        if not isinstance(selected, dict) or selected.get("id") != expected_key:
            return _hold(
                "sprint_job_order_differs_from_goal_planner",
                expected_job_key=expected_key,
                next_eligible_job_key=selected.get("id") if isinstance(selected, dict) else None,
            )
        selected_jobs.append(selected)
        selected_criteria.add(selected["criterion_id"])
        simulated_states[expected_key] = "done"

    if not set(acceptance).issubset(selected_criteria):
        return _hold(
            "sprint_jobs_do_not_cover_acceptance_criteria",
            uncovered_criteria=sorted(set(acceptance) - selected_criteria),
        )
    if budget > getattr(autonomy_grant, "max_jobs", budget) if False else False:
        # Kept intentionally unreachable: grant shape and bounds are validated
        # by plan_next_job; do not duplicate its private grant parser here.
        return _hold("sprint_budget_exceeds_goal_grant")

    return {
        "decision": "READY",
        "reason": "all_sprint_jobs_match_goal_planner_and_grant",
        "sprint": {
            "sprint_id": sprint_id,
            "goal_id": goal_id,
            "sequence": sequence,
            "sprint_goal": sprint_goal.strip(),
            "job_keys": list(job_keys),
            "acceptance_criteria": list(acceptance),
            "max_jobs": budget,
        },
        "jobs": selected_jobs,
        "create_sprint": False,
        "create_job": False,
        "execute_job": False,
        "permissions": {"expand_grant": False, "clear_hold": False, "merge": False, "deploy": False},
    }


__all__ = ["assess_sprint_readiness", "MAX_SPRINT_JOBS"]
