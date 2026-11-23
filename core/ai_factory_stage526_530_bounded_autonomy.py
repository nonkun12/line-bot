"""Stages 526-530: bounded autonomy policy declaration checks."""
from __future__ import annotations
from typing import Any

ALLOWED = {"read", "analyze", "propose", "test_in_sandbox"}
FORBIDDEN = {"merge", "deploy", "release", "permission_change", "hold_release", "production_write"}


def capability_scope_check(record: dict[str, Any]) -> dict[str, Any]:
    requested = set(record.get("requested_capabilities", []))
    unknown = requested - ALLOWED
    missing = not record.get("scope_ref") or record.get("hold") is not True
    blocked = bool(unknown) or missing
    return {"stage": 526, "status": "BLOCKED" if blocked else "DECLARATIONS_COMPLETE",
            "unknown_capabilities": sorted(unknown), "scope_missing": missing,
            "capabilities_granted": []}


def budget_check(record: dict[str, Any]) -> dict[str, Any]:
    limits = ("task_limit", "time_budget_ref", "resource_budget_ref")
    missing = [k for k in limits if not record.get(k)]
    if not isinstance(record.get("task_limit"), int) or record.get("task_limit", 0) <= 0:
        missing.append("task_limit_positive_integer")
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 527, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": sorted(set(missing)), "budget_enforced": False}


def forbidden_action_check(actions: list[str]) -> dict[str, Any]:
    blocked = sorted(set(actions) & FORBIDDEN)
    return {"stage": 528, "status": "BLOCKED" if blocked else "DECLARATIONS_COMPLETE",
            "forbidden_requested": blocked, "actions_executed": False}


def validate_handoff(record: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in ("handoff_target_ref", "handoff_reason_ref") if not record.get(k)]
    if record.get("handoff_required") is not True:
        missing.append("handoff_required")
    return {"stage": 529, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "handoff_triggered": False}


def autonomy_gate(scope: dict[str, Any], budget: dict[str, Any], actions: list[str],
                 handoff: dict[str, Any]) -> dict[str, Any]:
    checks = [capability_scope_check(scope), budget_check(budget),
              forbidden_action_check(actions), validate_handoff(handoff)]
    ready = all(x["status"] == "DECLARATIONS_COMPLETE" for x in checks)
    return {"stage": 530, "status": "READY_FOR_REVIEW" if ready else "BLOCKED",
            "hold": True, "autonomy_enabled": False,
            "capabilities_granted": [], "checks": checks}
