"""Stages 511-515: declarative recovery readiness checks; no recovery actions."""
from __future__ import annotations

from typing import Any

REQUIRED_INCIDENT = ("incident_id", "repair_ref", "failure_ref", "impact_scope")
REQUIRED_RECOVERY = ("recovery_plan_ref", "rollback_ref", "verification_ref")


def _missing(record: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    return [field for field in required_fields if not record.get(field)]


def validate_recovery_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate declared recovery evidence only; inputs are untrusted metadata."""
    missing = _missing(record, REQUIRED_INCIDENT + REQUIRED_RECOVERY)
    if record.get("recovery_status") not in {"planned", "verified", "not_applicable"}:
        missing.append("recovery_status")
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 511, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": sorted(set(missing)), "execution_allowed": False,
            "hold_release_allowed": False}


def compare_recovery_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Require distinct attempt IDs and evidence refs for a recovery review."""
    ids = [x.get("attempt_id") for x in attempts]
    refs = [x.get("evidence_ref") for x in attempts]
    missing = any(not x for x in ids + refs)
    duplicates = len(set(ids)) != len(ids) or len(set(refs)) != len(refs)
    return {"stage": 512, "status": "BLOCKED" if missing or duplicates or len(attempts) < 2 else "DECLARATIONS_COMPLETE",
            "missing_or_duplicate": missing or duplicates, "attempt_count": len(attempts),
            "execution_allowed": False}


def validate_recovery_boundary(record: dict[str, Any]) -> dict[str, Any]:
    forbidden = ("automatic_retry", "rollback_executed", "hold_cleared", "deployment_started")
    violations = [key for key in forbidden if record.get(key) is True]
    return {"stage": 513, "status": "BLOCKED" if violations else "DECLARATIONS_COMPLETE",
            "violations": violations, "side_effects_permitted": False}


def validate_post_recovery_tests(record: dict[str, Any]) -> dict[str, Any]:
    required = ("test_ref", "regression_ref", "independent_check_ref")
    missing = _missing(record, required)
    if record.get("tests_pass") is not True:
        missing.append("tests_pass")
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 514, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "merge_or_deploy_authorized": False}


def recovery_review_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    results = [validate_recovery_record(x) for x in records]
    passed = bool(records) and all(x["status"] == "DECLARATIONS_COMPLETE" for x in results)
    return {"stage": 515, "status": "READY_FOR_REVIEW" if passed else "BLOCKED",
            "records_checked": len(records), "hold": True,
            "recovery_execution_authorized": False, "results": results}
