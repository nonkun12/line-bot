"""Explicit independent-review gate for completed Goal child JOBs.

The executor and reviewer are separate injected callables. This module never
executes child work; it only persists a complete review result and, when all
criteria pass, asks the bounded orchestrator to plan one next JOB.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import goal_job_store
from goal_job_orchestrator import advance_goal

_ALLOWED = {"PASS", "FAIL", "UNKNOWN"}


def review_completed_goal(
    goal_id: str,
    *,
    evaluator: Callable[[dict[str, Any], list[dict[str, Any]]], object] | None,
    job_generator: Callable[[dict[str, Any], dict[str, str], dict[str, str]], object] | None = None,
) -> dict[str, Any]:
    """Review persisted child evidence and queue at most one next JOB.

    The evaluator must be supplied independently from the executor. Its result
    must cover every registered success criterion. PASS is additionally
    constrained by goal_job_store to criteria with completed child evidence
    whose checks all pass.
    """
    if evaluator is None:
        return {"decision": "HOLD", "reason": "independent_evaluator_required"}
    record = goal_job_store.get_goal(goal_id)
    if record is None:
        return {"decision": "HOLD", "reason": "goal_not_found"}

    children = goal_job_store.get_goal_child_jobs(goal_id)
    completed = [
        child for child in children
        if isinstance(child, dict) and child.get("status") in {"done", "completed"}
    ]
    if not completed:
        return {"decision": "HOLD", "reason": "no_completed_child_evidence"}

    try:
        reviewed = evaluator(record, children)
    except Exception as exc:
        return {
            "decision": "HOLD",
            "reason": "independent_review_failed",
            "error_type": type(exc).__name__,
        }

    criteria = record["goal"].get("success_criteria")
    expected = {
        item.get("id") for item in criteria
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(criteria, list) else set()
    if (
        not expected
        or not isinstance(reviewed, dict)
        or set(reviewed) != expected
        or any(not isinstance(value, str) or value not in _ALLOWED for value in reviewed.values())
    ):
        return {"decision": "HOLD", "reason": "review_result_must_cover_all_criteria"}

    try:
        updated = goal_job_store.update_goal_evidence(goal_id, reviewed)
    except (ValueError, PermissionError) as exc:
        return {
            "decision": "HOLD",
            "reason": "review_evidence_rejected",
            "detail": str(exc)[:240],
        }

    if not all(value == "PASS" for value in reviewed.values()):
        return {
            "decision": "HOLD",
            "reason": "independent_review_not_passed",
            "criterion_results": updated["criterion_results"],
        }

    continuation = advance_goal(goal_id, job_generator=job_generator)
    return {
        **continuation,
        "reviewed": True,
        "goal_id": goal_id,
        "criterion_results": updated["criterion_results"],
    }


__all__ = ["review_completed_goal"]
