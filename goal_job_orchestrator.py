"""Bounded Goal-to-child-JOB orchestration.

This module connects the deterministic planner, durable Goal store, and typed
worker. It runs only when a caller supplies both a real executor and an
independent evidence evaluator. It never merges, deploys, or clears HOLD.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import goal_job_store
import goal_job_worker
from scripts.goal_job_chain import MAX_AUTONOMOUS_JOBS_PER_GOAL, plan_next_job


def advance_goal(goal_id: str, *, job_generator: Callable[[dict[str, Any], dict[str, str], dict[str, str]], object] | None = None) -> dict[str, Any]:
    """Plan and idempotently persist at most one next child JOB."""
    record = goal_job_store.get_goal(goal_id)
    if record is None:
        return {"decision": "HOLD", "reason": "goal_not_found"}
    goal = record["goal"]
    evidence = record["criterion_results"]
    if not evidence:
        evidence = {item["id"]: "FAIL" for item in goal["success_criteria"]}
    states = goal_job_store.get_goal_job_states(goal_id)
    decision = plan_next_job(
        goal,
        evidence,
        states,
        autonomy_grant=record["autonomy_grant"],
    )
    generation_reasons = {
        "no_registered_job_for_unmet_criteria",
        "no_safe_next_job",
        "failed_job_requires_registered_repair",
    }
    if decision.get("decision") == "HOLD" and decision.get("reason") in generation_reasons and job_generator is not None:
        try:
            proposed = job_generator(record, evidence, states)
            if not isinstance(proposed, dict):
                return {"decision": "HOLD", "reason": "job_generator_returned_no_valid_child", "goal_id": goal_id}
            goal_job_store.register_child_job_definition(goal_id, proposed)
            refreshed = goal_job_store.get_goal(goal_id)
            if refreshed is None:
                return {"decision": "HOLD", "reason": "goal_disappeared_after_job_generation"}
            goal = refreshed["goal"]
            evidence = refreshed["criterion_results"]
            states = goal_job_store.get_goal_job_states(goal_id)
            decision = plan_next_job(
                goal,
                evidence,
                states,
                autonomy_grant=refreshed["autonomy_grant"],
            )
        except (ValueError, PermissionError) as exc:
            return {"decision": "HOLD", "reason": "generated_job_rejected", "detail": str(exc)[:240]}
        except Exception as exc:
            return {"decision": "HOLD", "reason": "job_generator_failed", "error_type": type(exc).__name__}
    if decision.get("decision") != "PROPOSE_CHILD_JOB":
        return decision

    job = decision["job"]
    dependencies = job.get("depends_on", [])
    parent_key = dependencies[0] if dependencies else None
    try:
        persisted = goal_job_store.persist_child_job(
            goal_id,
            job,
            parent_job_key=parent_key,
        )
    except (ValueError, PermissionError) as exc:
        return {"decision": "HOLD", "reason": "child_job_persistence_rejected", "detail": str(exc)[:240]}
    return {
        **decision,
        "decision": "CHILD_JOB_QUEUED",
        "job_record": persisted,
        "create_job": persisted["created"],
        "execute_job": False,
    }


def run_until_blocked(
    goal_id: str,
    *,
    executor: Callable[[dict[str, Any], dict[str, Any]], object] | None,
    evidence_evaluator: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]] | None,
    max_steps: int | None = None,
    job_generator: Callable[[dict[str, Any], dict[str, str], dict[str, str]], object] | None = None,
) -> dict[str, Any]:
    """Run a bounded chain until Goal completion, HOLD, or its step budget.

    The executor performs the child work. The separate evaluator must inspect
    the resulting evidence and return a complete criterion_id -> PASS/FAIL/
    UNKNOWN map. A worker result alone can never mark the Goal achieved.
    """
    if executor is None or evidence_evaluator is None:
        return {"decision": "HOLD", "reason": "executor_and_independent_evaluator_required"}
    record = goal_job_store.get_goal(goal_id)
    if record is None:
        return {"decision": "HOLD", "reason": "goal_not_found"}
    grant = record["autonomy_grant"]
    budget = grant["max_jobs"]
    if max_steps is None:
        max_steps = budget
    if type(max_steps) is not int or not 1 <= max_steps <= min(budget, MAX_AUTONOMOUS_JOBS_PER_GOAL):
        return {"decision": "HOLD", "reason": "step_budget_invalid"}

    for step in range(max_steps):
        planned = advance_goal(goal_id, job_generator=job_generator)
        if planned.get("decision") != "CHILD_JOB_QUEUED":
            return {**planned, "steps_executed": step}
        job_id = planned["job_record"]["job_id"]
        completed = goal_job_worker.run_once(executor, job_id=job_id)
        if completed is None:
            return {"decision": "HOLD", "reason": "child_job_claim_unavailable", "job_id": job_id, "steps_executed": step}
        try:
            evaluation = evidence_evaluator(goal_job_store.get_goal(goal_id), completed)
            goal_job_store.update_goal_evidence(goal_id, evaluation)
        except Exception as exc:
            return {
                "decision": "HOLD",
                "reason": "independent_evidence_evaluation_failed",
                "error_type": type(exc).__name__,
                "job_id": job_id,
                "steps_executed": step + 1,
            }

    final = advance_goal(goal_id, job_generator=job_generator)
    if final.get("decision") == "GOAL_ACHIEVED":
        return {**final, "steps_executed": max_steps}
    return {
        "decision": "HOLD",
        "reason": "autonomous_step_budget_reached",
        "goal_id": goal_id,
        "steps_executed": max_steps,
        "next_decision": final,
    }


__all__ = ["advance_goal", "run_until_blocked"]
