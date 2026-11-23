"""Stages 516-520: recurrence prevention and validation; declaration-only."""
from __future__ import annotations

from typing import Any

REQUIRED = ("cause_ref", "prevention_change_ref", "regression_test_ref", "monitoring_ref")


def recurrence_prevention_check(record: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED if not record.get(key)]
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    if record.get("prevention_verified") is not True:
        missing.append("prevention_verified")
    return {"stage": 516, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "change_execution_allowed": False}


def compare_incidents(records: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [x.get("incident_ref") for x in records]
    missing = any(not ref for ref in refs)
    duplicate = len(set(refs)) != len(refs)
    return {"stage": 517, "status": "BLOCKED" if missing or duplicate else "DECLARATIONS_COMPLETE",
            "missing_refs": missing, "duplicate_refs": duplicate, "count": len(records)}


def validate_monitoring_window(record: dict[str, Any]) -> dict[str, Any]:
    required = ("window_ref", "baseline_ref", "observation_ref")
    missing = [key for key in required if not record.get(key)]
    if record.get("window_closed") is not True:
        missing.append("window_closed")
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 518, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "promotion_allowed": False}


def validate_claims(record: dict[str, Any]) -> dict[str, Any]:
    unsupported = [claim for claim in record.get("claims", []) if claim in
                   {"root_cause_proven", "recurrence_eliminated", "general_capability_improved"}]
    return {"stage": 519, "status": "BLOCKED" if unsupported else "DECLARATIONS_COMPLETE",
            "unsupported_claims": unsupported, "causal_claims_allowed": False}


def recurrence_gate(recovery: dict[str, Any], incidents: list[dict[str, Any]],
                   monitoring: dict[str, Any], claims: dict[str, Any]) -> dict[str, Any]:
    checks = [recurrence_prevention_check(recovery), compare_incidents(incidents),
              validate_monitoring_window(monitoring), validate_claims(claims)]
    passed = all(item["status"] == "DECLARATIONS_COMPLETE" for item in checks)
    return {"stage": 520, "status": "READY_FOR_REVIEW" if passed else "BLOCKED",
            "hold": True, "repair_or_promotion_authorized": False, "checks": checks}
