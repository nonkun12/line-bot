"""Authorization-boundary and audit-closeout declarations (Stages 596-600)."""
from __future__ import annotations

from datetime import datetime, timezone

REQUIRED = (
    "authorization_ref", "authorization_owner_ref", "authorization_scope",
    "authorization_status", "authorization_expires_at", "authorization_revoked",
    "residual_risks", "unresolved_issues", "audit_record_ref",
    "closeout_owner_ref", "closeout_status", "automatic_execution",
    "production_change", "model_change",
)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _text_list(value, *, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
        and len(value) == len(set(value))
    )


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


def validate_authorization_closeout(record, *, now=None):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    missing = [key for key in REQUIRED if key not in record or record[key] is None]
    issues = []
    for field in (
        "authorization_ref", "authorization_owner_ref", "authorization_scope",
        "audit_record_ref", "closeout_owner_ref",
    ):
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")

    if record.get("authorization_status") not in ("NOT_GRANTED", "GRANTED_DECLARED"):
        issues.append("authorization_status_invalid")
    expiry = _timestamp(record.get("authorization_expires_at"))
    if expiry is None:
        issues.append("authorization_expires_at_invalid")

    current = now
    if current is None:
        current = datetime.now(timezone.utc)
    elif isinstance(current, str):
        current = _timestamp(current)
    if current is None:
        issues.append("now_invalid")
    elif expiry is not None and expiry <= current:
        issues.append("authorization_expired")

    if record.get("authorization_revoked") is not False:
        issues.append("authorization_revoked_or_unknown")
    if not _text_list(record.get("residual_risks")):
        issues.append("residual_risks_invalid")
    if not _text_list(record.get("unresolved_issues"), allow_empty=True):
        issues.append("unresolved_issues_invalid")
    if record.get("closeout_status") not in ("OPEN", "CLOSED_WITH_FOLLOW_UP"):
        issues.append("closeout_status_invalid")
    if record.get("automatic_execution") is not False:
        issues.append("automatic_execution_must_be_false")
    if record.get("production_change") is not False:
        issues.append("production_change_must_be_false")
    if record.get("model_change") is not False:
        issues.append("model_change_must_be_false")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
        "authorization_authenticity_verified": False,
        "scope_enforcement_verified": False,
        "audit_log_immutability_verified": False,
    }


def stage_600_authorization_closeout_gate(record, *, now=None):
    result = validate_authorization_closeout(record, now=now)
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "READY_FOR_INDEPENDENT_REVIEW",
        "execution_authorized": False,
        "automatic_acceptance": False,
        "automatic_release": False,
        "automatic_resume": False,
    }
