"""Stages 521-525: declaration-only audit evidence checks."""
from __future__ import annotations
from typing import Any

REQUIRED = ("event_id", "event_type", "actor_ref", "target_ref", "timestamp", "evidence_ref")


def audit_event_check(event: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED if not event.get(k)]
    if event.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 521, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "actions_authorized": False}


def audit_chain_check(events: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [e.get("event_id") for e in events]
    refs = [e.get("evidence_ref") for e in events]
    bad = not events or any(not x for x in ids + refs) or len(ids) != len(set(ids))
    return {"stage": 522, "status": "BLOCKED" if bad else "DECLARATIONS_COMPLETE",
            "event_count": len(events), "duplicate_event_ids": len(ids) != len(set(ids)),
            "missing_refs": any(not x for x in ids + refs), "chain_integrity_proven": False}


def validate_audit_retention(record: dict[str, Any]) -> dict[str, Any]:
    required = ("retention_policy_ref", "archive_ref", "access_control_ref")
    missing = [k for k in required if not record.get(k)]
    if record.get("retention_declared") is not True:
        missing.append("retention_declared")
    return {"stage": 523, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "immutable_storage_verified": False}


def validate_audit_access(record: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in ("access_review_ref", "reviewer_ref") if not record.get(k)]
    if record.get("review_complete") is not True:
        missing.append("review_complete")
    if record.get("hold") is not True:
        missing.append("hold_must_remain_true")
    return {"stage": 524, "status": "BLOCKED" if missing else "DECLARATIONS_COMPLETE",
            "missing": missing, "permission_changes_allowed": False}


def audit_gate(event: dict[str, Any], events: list[dict[str, Any]],
               retention: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    checks = [audit_event_check(event), audit_chain_check(events),
              validate_audit_retention(retention), validate_audit_access(access)]
    ready = all(x["status"] == "DECLARATIONS_COMPLETE" for x in checks)
    return {"stage": 525, "status": "READY_FOR_REVIEW" if ready else "BLOCKED",
            "hold": True, "audit_proof_verified": False,
            "mutations_authorized": False, "checks": checks}
