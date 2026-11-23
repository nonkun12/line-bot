"""Fail-closed candidate decision governance declarations (Stages 591-595)."""
from __future__ import annotations

from datetime import datetime, timezone

DISPOSITIONS = {"ACCEPT_FOR_FURTHER_TESTING", "REJECT", "DEFER"}
REQUIRED = (
    "decision_id", "candidate_ref", "evidence_refs", "decision_basis",
    "disposition", "decision_scope", "decision_owner_ref", "decided_at",
    "valid_until", "dissent_records", "revalidation_triggers",
    "automatic_execution", "production_change", "model_change",
)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _unique_text_list(value, *, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
        and len(value) == len(set(value))
    )


def validate_candidate_decision(record, *, now=None):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    missing = [key for key in REQUIRED if key not in record or record[key] is None]
    issues = []
    for field in ("decision_id", "candidate_ref", "decision_scope", "decision_owner_ref"):
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")
    for field in ("evidence_refs", "decision_basis", "revalidation_triggers"):
        if not _unique_text_list(record.get(field)):
            issues.append(f"{field}_invalid")
    if not _unique_text_list(record.get("dissent_records"), allow_empty=True):
        issues.append("dissent_records_invalid")
    if record.get("disposition") not in DISPOSITIONS:
        issues.append("disposition_invalid")

    decided = _timestamp(record.get("decided_at"))
    expires = _timestamp(record.get("valid_until"))
    if decided is None:
        issues.append("decided_at_invalid")
    if expires is None:
        issues.append("valid_until_invalid")
    if decided is not None and expires is not None and expires <= decided:
        issues.append("decision_validity_window_invalid")

    current = now
    if current is None:
        current = datetime.now(timezone.utc)
    elif isinstance(current, str):
        current = _timestamp(current)
    if current is None:
        issues.append("now_invalid")
    elif expires is not None and expires <= current:
        issues.append("decision_expired")

    if record.get("automatic_execution") is not False:
        issues.append("automatic_execution_must_be_false")
    if record.get("production_change") is not False:
        issues.append("production_change_must_be_false")
    if record.get("model_change") is not False:
        issues.append("model_change_must_be_false")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "DECISION_DECLARATION_COMPLETE", "missing": [], "issues": [],
        "decision_authenticity_verified": False, "candidate_accepted": False,
    }


def stage_595_decision_governance_gate(record, *, now=None):
    result = validate_candidate_decision(record, now=now)
    disposition = record.get("disposition") if isinstance(record, dict) else None
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "AUTHORIZATION_REQUIRED",
        "disposition": disposition if result["status"] != "BLOCKED" else None,
        "automatic_acceptance": False,
        "automatic_release": False,
    }
