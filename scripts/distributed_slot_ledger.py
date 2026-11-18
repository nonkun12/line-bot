"""Fail-closed contract for a future durable distributed-slot ledger.

This module is intentionally pure: it does not read/write state, claim work,
renew leases, dispatch workflows, or authorize retries. It defines the minimum
record shape and permitted one-way lifecycle transitions for later integration.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

SCHEDULE_WORKFLOW_ID = 357086091
SLOT_STATUSES = frozenset({"PENDING", "CLAIMED", "COMPLETED", "FAILED", "HELD"})
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "HELD"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SLOT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:(17|47):00Z$")


def expected_idempotency_key(slot_id: str, workflow_id: int = SCHEDULE_WORKFLOW_ID) -> str:
    """Return the stable key for one known workflow schedule slot."""
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ValueError("workflow_id must be a positive integer")
    if not isinstance(slot_id, str) or not SLOT_ID_RE.fullmatch(slot_id):
        raise ValueError("slot_id must be a UTC :17 or :47 schedule timestamp")
    material = f"distributed-loop:{workflow_id}:{slot_id}"
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def _valid_slot_id(value: Any) -> bool:
    """Validate both the slot format and the actual UTC calendar timestamp."""
    if not isinstance(value, str) or not SLOT_ID_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_slot_record(record: Any) -> list[str]:
    """Return validation errors; an empty list means the record is well-formed."""
    if not isinstance(record, dict):
        return ["record must be an object"]

    errors: list[str] = []
    slot_id = record.get("slot_id")
    if not _valid_slot_id(slot_id):
        errors.append("slot_id must be a real UTC :17 or :47 calendar timestamp")

    workflow_id = record.get("workflow_id")
    if type(workflow_id) is not int or workflow_id != SCHEDULE_WORKFLOW_ID:
        errors.append("workflow_id must match the designated distributed-loop workflow")

    key = record.get("idempotency_key")
    if not isinstance(key, str) or not SHA256_RE.fullmatch(key):
        errors.append("idempotency_key must be a lowercase SHA-256 hex digest")
    elif _valid_slot_id(slot_id) and type(workflow_id) is int and workflow_id == SCHEDULE_WORKFLOW_ID:
        if key != expected_idempotency_key(slot_id, workflow_id):
            errors.append("idempotency_key does not match workflow_id and slot_id")

    status = record.get("status")
    if not isinstance(status, str) or status not in SLOT_STATUSES:
        errors.append("status is not a supported lifecycle state")
        status = None

    attempt = record.get("attempt")
    if type(attempt) is not int or attempt < 0:
        errors.append("attempt must be a non-negative integer")
    elif status == "PENDING" and attempt != 0:
        errors.append("PENDING records must have attempt=0")
    elif status in {"CLAIMED", "COMPLETED", "FAILED", "HELD"} and attempt < 1:
        errors.append("claimed or terminal records must have attempt>=1")

    created_at = record.get("created_at")
    if not _valid_timestamp(created_at):
        errors.append("created_at must be an offset-aware timestamp")

    if status == "CLAIMED":
        lease = record.get("lease")
        if not isinstance(lease, dict):
            errors.append("CLAIMED records require a lease object")
        else:
            for field in ("owner", "run_id"):
                if not isinstance(lease.get(field), str) or not lease[field].strip():
                    errors.append(f"CLAIMED lease requires non-empty {field}")
            for field in ("acquired_at", "expires_at"):
                if not _valid_timestamp(lease.get(field)):
                    errors.append(f"CLAIMED lease requires valid {field}")
            acquired = lease.get("acquired_at")
            expires = lease.get("expires_at")
            if _valid_timestamp(acquired) and _valid_timestamp(expires):
                a = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
                e = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if e <= a:
                    errors.append("lease expires_at must be later than acquired_at")

    if status == "COMPLETED":
        evidence = record.get("completion_evidence")
        if not isinstance(evidence, dict):
            errors.append("COMPLETED records require completion_evidence")
        else:
            if evidence.get("verified") is not True:
                errors.append("completion evidence must be explicitly verified")
            if not isinstance(evidence.get("task_id"), str) or not evidence["task_id"].strip():
                errors.append("completion evidence requires task_id")
            if not isinstance(evidence.get("completed_at"), str) or not _valid_timestamp(evidence["completed_at"]):
                errors.append("completion evidence requires valid completed_at")
            if not isinstance(evidence.get("evidence_sha"), str) or not SHA1_RE.fullmatch(evidence["evidence_sha"]):
                errors.append("completion evidence requires a lowercase SHA-1 commit/evidence SHA")

    if status == "FAILED" and (not isinstance(record.get("failure_reason"), str) or not record["failure_reason"].strip()):
        errors.append("FAILED records require failure_reason")
    if status == "HELD" and (not isinstance(record.get("hold_reason"), str) or not record["hold_reason"].strip()):
        errors.append("HELD records require hold_reason")

    return errors


def transition_decision(current_status: str, next_status: str) -> dict[str, Any]:
    """Evaluate a lifecycle transition without changing a record or granting work."""
    allowed = {
        "PENDING": {"CLAIMED", "HELD"},
        "CLAIMED": {"COMPLETED", "FAILED", "HELD"},
        "COMPLETED": set(),
        "FAILED": set(),
        "HELD": set(),
    }
    if not isinstance(current_status, str) or not isinstance(next_status, str):
        return {"allowed": False, "reason": "unknown_lifecycle_state"}
    if current_status not in SLOT_STATUSES or next_status not in SLOT_STATUSES:
        return {"allowed": False, "reason": "unknown_lifecycle_state"}
    if current_status == "FAILED" and next_status == "PENDING":
        return {"allowed": False, "reason": "retry_requires_separate_human_review"}
    if next_status in allowed[current_status]:
        return {"allowed": True, "reason": "contract_transition_only"}
    if current_status in TERMINAL_STATUSES:
        return {"allowed": False, "reason": "terminal_state_no_automatic_transition"}
    if current_status == "CLAIMED" and next_status == "CLAIMED":
        return {"allowed": False, "reason": "lease_renewal_not_implemented"}
    return {"allowed": False, "reason": "transition_not_in_allowlist"}
