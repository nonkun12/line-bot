#!/usr/bin/env python3
"""Deterministic, provider-free Orchestrator planner.

This module plans work only. It never executes tasks, edits the repository,
creates branches/PRs, merges, deploys, or releases a HOLD.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VALID_STATES = {"pending", "running", "done", "failed", "blocked", "cancelled"}
MAX_TASKS = 500
MAX_RUNTIME_MINUTES = 2000


class PlanError(ValueError):
    """Input cannot be safely planned."""


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanError(f"invalid_{field}")
    return value


def _validate(document: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(document, dict):
        raise PlanError("input_must_be_object")
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise PlanError("invalid_tasks_list")
    if document.get("schema_version") != 1:
        raise PlanError("unsupported_schema_version")

    if "global_hold" not in document:
        raise PlanError("missing_global_hold")
    global_hold = document["global_hold"]
    if not isinstance(global_hold, bool):
        raise PlanError("invalid_global_hold")
    budget = document.get("budget")
    if not isinstance(budget, dict):
        raise PlanError("missing_budget")
    limit = _nonnegative_int(budget.get("limit_minutes"), "budget_limit")
    consumed = _nonnegative_int(budget.get("consumed_minutes"), "budget_consumed")
    reserved = _nonnegative_int(budget.get("reserved_minutes"), "budget_reserved")
    if limit > MAX_RUNTIME_MINUTES or consumed > MAX_RUNTIME_MINUTES or reserved > MAX_RUNTIME_MINUTES:
        raise PlanError("budget_exceeds_hard_cap")
    if consumed + reserved > limit:
        raise PlanError("budget_accounting_exceeds_limit")

    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise PlanError("task_must_be_object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 120:
            raise PlanError("invalid_task_id")
        if task_id in by_id:
            raise PlanError("duplicate_task_id")
        status = task.get("status", "pending")
        if not isinstance(status, str) or status not in VALID_STATES:
            raise PlanError("invalid_task_status")
        priority = task.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100:
            raise PlanError("invalid_task_priority")
        deps = task.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(x, str) or not x for x in deps):
            raise PlanError("invalid_dependencies")
        if len(deps) != len(set(deps)) or task_id in deps:
            raise PlanError("duplicate_or_self_dependency")
        estimate = _nonnegative_int(task.get("estimated_minutes", 0), "task_estimate")
        if estimate > MAX_RUNTIME_MINUTES:
            raise PlanError("task_estimate_exceeds_hard_cap")
        approval = task.get("execution_approved", False)
        if not isinstance(approval, bool):
            raise PlanError("invalid_execution_approval")
        by_id[task_id] = {
            **task,
            "status": status,
            "priority": priority,
            "depends_on": deps,
            "estimated_minutes": estimate,
            "execution_approved": approval,
        }

    for task in by_id.values():
        if any(dep not in by_id for dep in task["depends_on"]):
            raise PlanError("dependency_not_found")

    # Detect dependency cycles before calculating readiness.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise PlanError("dependency_cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in by_id[task_id]["depends_on"]:
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)
    return {"global_hold": global_hold, "budget": budget}, by_id


def build_plan(document: Any) -> dict[str, Any]:
    """Return a deterministic, read-only execution plan."""
    meta, tasks = _validate(document)
    budget = meta["budget"]
    remaining = budget["limit_minutes"] - budget["consumed_minutes"] - budget["reserved_minutes"]
    reasons: list[str] = []
    if meta["global_hold"]:
        reasons.append("global_hold")
    if remaining <= 0:
        reasons.append("budget_exhausted")

    rows = []
    for task_id, task in tasks.items():
        deps = task["depends_on"]
        if task["status"] in {"done", "cancelled"}:
            state, reason = task["status"].upper(), "terminal_state"
        elif task["status"] == "running":
            state, reason = "IN_PROGRESS", "already_running"
        elif task["status"] in {"failed", "blocked"}:
            state, reason = "BLOCKED", f"task_{task['status']}"
        elif any(tasks[dep]["status"] != "done" for dep in deps):
            state, reason = "WAITING", "dependencies_incomplete"
        else:
            state, reason = "READY", None
        rows.append({
            "id": task_id,
            "priority": task["priority"],
            "estimated_minutes": task["estimated_minutes"],
            "execution_approved": task["execution_approved"],
            "planning_state": state,
            "reason": reason,
        })

    ready = sorted(
        (row for row in rows if row["planning_state"] == "READY"),
        key=lambda row: (-row["priority"], row["id"]),
    )
    # Planning is deliberately independent from execution authorization.
    # The approval boolean is caller-supplied metadata and is NOT verified
    # against an authoritative approval record in this phase.
    selected = None
    if not reasons and ready:
        fitting = [
            row for row in ready
            if row["estimated_minutes"] <= remaining
        ]
        if fitting:
            selected = fitting[0]["id"]
            # No authoritative approval verifier is wired in yet. This remains
            # true even when a task carries execution_approved=true.
            reasons.append("approval_evidence_unverified")
        else:
            reasons.append("insufficient_remaining_budget")
    elif tasks and not ready and not reasons:
        reasons.append("no_ready_tasks")

    return {
        "schema_version": 1,
        "status": "HOLD" if "global_hold" in reasons or "budget_exhausted" in reasons
        or "insufficient_remaining_budget" in reasons or "no_ready_tasks" in reasons
        else ("PLAN_READY" if selected else "NO_TASK"),
        "global_hold": meta["global_hold"],
        "budget": {
            "limit_minutes": budget["limit_minutes"],
            "consumed_minutes": budget["consumed_minutes"],
            "reserved_minutes": budget["reserved_minutes"],
            "remaining_minutes": remaining,
        },
        "tasks": sorted(rows, key=lambda row: (-row["priority"], row["id"])),
        "selected_candidate": selected,
        "execution_authorized": False,
        "approval_evidence_verified": False,
        "budget_evidence_verified": False,
        "execution_performed": False,
        "dispatch_performed": False,
        "repository_modified": False,
        "push_performed": False,
        "pull_request_created": False,
        "merge_performed": False,
        "deployment_performed": False,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        result = build_plan(document)
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        result = {
            "schema_version": 1,
            "status": "HOLD",
            "execution_performed": False,
            "dispatch_performed": False,
            "repository_modified": False,
            "reasons": [str(exc)[:160]],
        }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(rendered)
    return 0 if result["status"] in {"PLAN_READY", "NO_TASK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
