"""Pure policy engine for goal-driven autonomous continuation.

This module plans one safe next action. It never executes tasks, writes state,
dispatches workflows, changes permissions, merges, or deploys.
"""
from __future__ import annotations

from typing import Any

TASK_STATES = frozenset({"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "HELD"})
SAFE_KINDS = frozenset({"READ_ONLY", "TEST", "DRAFT_PR"})
BLOCKED_KINDS = frozenset({"MERGE", "DEPLOY", "PERMISSION_CHANGE", "SECRET_CHANGE", "PRODUCTION_WRITE"})


def _is_true(value: Any) -> bool:
    return value is True


def evaluate_goal(goal: Any) -> dict[str, Any]:
    """Return COMPLETE, CONTINUE, HOLD, or INVALID with one bounded next action."""
    if not isinstance(goal, dict):
        return {"decision": "INVALID", "reason": "goal_must_be_object"}

    goal_id = goal.get("goal_id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        return {"decision": "INVALID", "reason": "goal_id_required"}
    if not isinstance(goal.get("objective"), str) or not goal["objective"].strip():
        return {"decision": "INVALID", "reason": "objective_required"}

    criteria = goal.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        return {"decision": "INVALID", "reason": "acceptance_criteria_required"}
    criterion_ids: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            return {"decision": "INVALID", "reason": "criterion_schema_invalid"}
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip() or criterion_id in criterion_ids:
            return {"decision": "INVALID", "reason": "criterion_id_missing_or_duplicate"}
        criterion_ids.add(criterion_id)

    if all(c.get("verified") is True for c in criteria):
        # A goal is complete only when every criterion has a verifiable evidence ref.
        if all(isinstance(c.get("evidence_ref"), str) and c["evidence_ref"].strip()
               for c in criteria):
            return {"decision": "COMPLETE", "reason": "all_acceptance_criteria_verified"}

    if goal.get("kill_switch") is True:
        return {"decision": "HOLD", "reason": "kill_switch_active"}
    if goal.get("safety_gate") is not True:
        return {"decision": "HOLD", "reason": "safety_gate_not_explicitly_passed"}

    tasks = goal.get("tasks")
    if not isinstance(tasks, list):
        return {"decision": "INVALID", "reason": "tasks_must_be_list"}

    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            return {"decision": "INVALID", "reason": "task_must_be_object"}
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            return {"decision": "INVALID", "reason": "task_id_missing_or_duplicate"}
        seen.add(task_id)
        if task.get("status") not in TASK_STATES:
            return {"decision": "INVALID", "reason": "unsupported_task_status"}
        priority = task.get("priority", 0)
        if type(priority) is not int:
            return {"decision": "INVALID", "reason": "task_priority_must_be_integer"}

    # Any in-flight task must be reconciled before another task is selected.
    in_flight = [t for t in tasks if t["status"] == "IN_PROGRESS"]
    if in_flight:
        if len(in_flight) > 1:
            return {"decision": "HOLD", "reason": "multiple_in_flight_tasks"}
        return {"decision": "HOLD", "reason": "in_flight_task_requires_reconciliation",
                "task_id": in_flight[0]["task_id"]}

    # Failures and holds are never silently retried or released.
    blocked = [t for t in tasks if t["status"] in {"FAILED", "HELD"}]
    if blocked:
        return {"decision": "HOLD", "reason": "failed_or_held_task_requires_review",
                "task_ids": [t["task_id"] for t in blocked]}

    completed = {t["task_id"] for t in tasks if t["status"] == "COMPLETED"}
    eligible = []
    for task in tasks:
        deps = task.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or not d.strip() for d in deps):
            return {"decision": "INVALID", "reason": "task_dependencies_invalid"}
        if len(deps) != len(set(deps)) or task["task_id"] in deps:
            return {"decision": "INVALID", "reason": "task_dependencies_duplicate_or_self_referential"}
        if any(dep not in seen for dep in deps):
            return {"decision": "INVALID", "reason": "unknown_task_dependency"}
        if task["status"] != "PENDING":
            continue
        if not set(deps).issubset(completed):
            continue
        eligible.append(task)

    if not eligible:
        return {"decision": "HOLD", "reason": "goal_incomplete_but_no_eligible_task"}

    # Stable priority ordering prevents run-to-run task drift.
    eligible.sort(key=lambda t: (-int(t.get("priority", 0)), t["task_id"]))
    task = eligible[0]
    kind = task.get("kind")
    if kind in BLOCKED_KINDS:
        return {"decision": "HOLD", "reason": "action_kind_forbidden",
                "task_id": task["task_id"]}
    if kind not in SAFE_KINDS:
        return {"decision": "HOLD", "reason": "action_kind_not_allowlisted",
                "task_id": task["task_id"]}
    if task.get("execution_authorized") is not True:
        reason = ("draft_pr_requires_explicit_task_authorization" if kind == "DRAFT_PR"
                  else "task_execution_not_explicitly_authorized")
        return {"decision": "HOLD", "reason": reason, "task_id": task["task_id"]}
    paths = task.get("allowed_paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p.strip() for p in paths):
        return {"decision": "HOLD", "reason": "allowed_paths_invalid",
                "task_id": task["task_id"]}
    return {"decision": "CONTINUE", "reason": "next_task_selected",
            "task_id": task["task_id"], "kind": kind,
            "allowed_paths": sorted(set(paths)), "max_tasks": 1}
