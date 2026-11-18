"""Pure policy engine for goal-driven autonomous continuation.

This module plans one safe next action. It never executes tasks, writes state,
dispatches workflows, changes permissions, merges, or deploys.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

TASK_STATES = frozenset({"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "HELD"})
SAFE_KINDS = frozenset({"READ_ONLY", "TEST", "DRAFT_PR"})
BLOCKED_KINDS = frozenset({"MERGE", "DEPLOY", "PERMISSION_CHANGE", "SECRET_CHANGE", "PRODUCTION_WRITE"})

MAX_TASKS = 500
MAX_DEPENDENCIES_PER_TASK = 100
MAX_ACCEPTANCE_CRITERIA = 100
MAX_ALLOWED_PATHS = 100
MAX_PATH_LENGTH = 512
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_CRITERION_EVIDENCE_RE = re.compile(r"^(commit:[0-9a-f]{40}|pr:[1-9][0-9]*|artifact:[A-Za-z0-9._/-]{1,200})$")
_PROTECTED_PARTS = frozenset({
    ".git", ".github", ".env", ".envrc", ".ssh", ".aws", ".config",
    "secrets", "secret", "credentials", "credential", "codeowners",
})


def _safe_relative_path(value: Any) -> bool:
    """Reject absolute, traversing, ambiguous, protected, and cross-platform paths."""
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        return False
    if value != value.strip() or "\\" in value or "\x00" in value:
        return False
    if value.startswith(("/", "~")):
        return False
    parts = value.rstrip("/").split("/")
    if any(not part or part != part.strip() or part in {".", ".."} for part in parts):
        return False
    if any(":" in part for part in parts):
        return False
    if any(part.lower() in _PROTECTED_PARTS for part in parts):
        return False
    if any(part.lower().startswith((".env.", "secret", "credential")) for part in parts):
        return False
    return True


def _valid_completion_evidence(task: dict[str, Any]) -> bool:
    """Validate task-bound evidence shape; integration must authenticate the record."""
    evidence = task.get("completion_evidence")
    if not isinstance(evidence, dict):
        return False
    if evidence.get("task_id") != task.get("task_id") or evidence.get("verified") is not True:
        return False
    evidence_sha = evidence.get("evidence_sha")
    if not isinstance(evidence_sha, str) or not _SHA1_RE.fullmatch(evidence_sha):
        return False
    verification_ref = evidence.get("verification_ref")
    if not isinstance(verification_ref, str) or not verification_ref.strip():
        return False
    completed_at = evidence.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at.strip():
        return False
    try:
        timestamp = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def _valid_criterion_evidence(value: Any) -> bool:
    return isinstance(value, str) and _CRITERION_EVIDENCE_RE.fullmatch(value) is not None


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
    if not isinstance(criteria, list) or not criteria or len(criteria) > MAX_ACCEPTANCE_CRITERIA:
        return {"decision": "INVALID", "reason": "acceptance_criteria_count_invalid"}
    criterion_ids: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            return {"decision": "INVALID", "reason": "criterion_schema_invalid"}
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip() or criterion_id in criterion_ids:
            return {"decision": "INVALID", "reason": "criterion_id_missing_or_duplicate"}
        criterion_ids.add(criterion_id)

    # Fail closed: only the literal boolean False means the kill switch is off.
    if goal.get("kill_switch") is not False:
        return {"decision": "HOLD", "reason": "kill_switch_active_or_invalid"}
    if goal.get("safety_gate") is not True:
        return {"decision": "HOLD", "reason": "safety_gate_not_explicitly_passed"}

    tasks = goal.get("tasks")
    if not isinstance(tasks, list):
        return {"decision": "INVALID", "reason": "tasks_must_be_list"}
    if len(tasks) > MAX_TASKS:
        return {"decision": "INVALID", "reason": "task_count_exceeds_limit"}

    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            return {"decision": "INVALID", "reason": "task_must_be_object"}
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            return {"decision": "INVALID", "reason": "task_id_missing_or_duplicate"}
        seen.add(task_id)
        status = task.get("status")
        if not isinstance(status, str) or status not in TASK_STATES:
            return {"decision": "INVALID", "reason": "unsupported_task_status"}
        if type(task.get("priority", 0)) is not int:
            return {"decision": "INVALID", "reason": "task_priority_must_be_integer"}

    graph: dict[str, list[str]] = {}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in seen}
    indegree: dict[str, int] = {}
    for task in tasks:
        deps = task.get("depends_on", [])
        if (not isinstance(deps, list) or len(deps) > MAX_DEPENDENCIES_PER_TASK
                or any(not isinstance(dep, str) or not dep.strip() for dep in deps)):
            return {"decision": "INVALID", "reason": "task_dependencies_invalid"}
        if len(deps) != len(set(deps)) or task["task_id"] in deps:
            return {"decision": "INVALID", "reason": "task_dependencies_duplicate_or_self_referential"}
        if any(dep not in seen for dep in deps):
            return {"decision": "INVALID", "reason": "unknown_task_dependency"}
        graph[task["task_id"]] = deps
        indegree[task["task_id"]] = len(deps)
        for dep in deps:
            dependents[dep].append(task["task_id"])

    # Iterative Kahn traversal avoids recursion-depth failures.
    ready = [task_id for task_id, degree in indegree.items() if degree == 0]
    visited_count = 0
    while ready:
        current = ready.pop()
        visited_count += 1
        for child in dependents[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited_count != len(graph):
        return {"decision": "INVALID", "reason": "cyclic_task_dependencies"}

    completed: set[str] = set()
    for task in tasks:
        if task["status"] == "COMPLETED":
            if not _valid_completion_evidence(task):
                return {"decision": "HOLD", "reason": "completed_task_evidence_invalid",
                        "task_id": task["task_id"]}
            completed.add(task["task_id"])

    in_flight = [task for task in tasks if task["status"] == "IN_PROGRESS"]
    if in_flight:
        if len(in_flight) > 1:
            return {"decision": "HOLD", "reason": "multiple_in_flight_tasks"}
        return {"decision": "HOLD", "reason": "in_flight_task_requires_reconciliation",
                "task_id": in_flight[0]["task_id"]}

    blocked = [task for task in tasks if task["status"] in {"FAILED", "HELD"}]
    if blocked:
        return {"decision": "HOLD", "reason": "failed_or_held_task_requires_review",
                "task_ids": [task["task_id"] for task in blocked]}

    criteria_complete = all(
        criterion.get("verified") is True and _valid_criterion_evidence(criterion.get("evidence_ref"))
        for criterion in criteria
    )
    if criteria_complete:
        if len(completed) != len(tasks):
            return {"decision": "HOLD", "reason": "acceptance_criteria_met_but_tasks_incomplete"}
        return {"decision": "COMPLETE", "reason": "all_acceptance_criteria_verified"}

    eligible = [
        task for task in tasks
        if task["status"] == "PENDING" and set(graph[task["task_id"]]).issubset(completed)
    ]
    if not eligible:
        return {"decision": "HOLD", "reason": "goal_incomplete_but_no_eligible_task"}

    eligible.sort(key=lambda task: (-task.get("priority", 0), task["task_id"]))
    task = eligible[0]
    kind = task.get("kind")
    if not isinstance(kind, str):
        return {"decision": "HOLD", "reason": "action_kind_not_allowlisted",
                "task_id": task["task_id"]}
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
    if (not isinstance(paths, list) or len(paths) > MAX_ALLOWED_PATHS
            or any(not _safe_relative_path(path) for path in paths)):
        return {"decision": "HOLD", "reason": "allowed_paths_invalid",
                "task_id": task["task_id"]}
    if kind == "DRAFT_PR" and not paths:
        return {"decision": "HOLD", "reason": "draft_pr_requires_explicit_paths",
                "task_id": task["task_id"]}
    return {"decision": "CONTINUE", "reason": "next_task_selected",
            "task_id": task["task_id"], "kind": kind,
            "allowed_paths": sorted(set(paths)), "max_tasks": 1}
