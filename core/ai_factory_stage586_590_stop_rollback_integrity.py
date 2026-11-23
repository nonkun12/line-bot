"""Fail-closed stop and rollback readiness declarations (Stages 586-590)."""
from __future__ import annotations


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _text_list(value, *, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
    )


def validate_stop_rollback(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    required = (
        "stop_conditions", "triggered_stop_conditions", "guardrail_checks",
        "rollback_plan_ref", "rollback_scope", "data_loss_assessment",
        "rollback_authorized", "rollback_executed", "production_change",
    )
    missing = [key for key in required if key not in record or record[key] is None]
    issues = []

    if not _text_list(record.get("stop_conditions")):
        issues.append("stop_conditions_invalid")
    triggered = record.get("triggered_stop_conditions")
    if not _text_list(triggered, allow_empty=True):
        issues.append("triggered_stop_conditions_invalid")
    elif triggered:
        issues.append("stop_condition_triggered")

    checks = record.get("guardrail_checks")
    if not isinstance(checks, list) or not checks:
        issues.append("guardrail_checks_invalid")
    else:
        seen = set()
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                issues.append(f"guardrail_check_{index}_invalid")
                continue
            identity, status = check.get("id"), check.get("status")
            if not _text(identity) or identity in seen:
                issues.append(f"guardrail_check_{index}_identity_invalid")
            if _text(identity):
                seen.add(identity)
            if status not in ("PASS", "FAIL", "UNKNOWN"):
                issues.append(f"guardrail_check_{index}_status_invalid")
            elif status != "PASS":
                issues.append(f"guardrail_check_{index}_{status.lower()}")

    if not _text(record.get("rollback_plan_ref")):
        issues.append("rollback_plan_ref_invalid")
    if not _text(record.get("rollback_scope")):
        issues.append("rollback_scope_invalid")
    if not _text(record.get("data_loss_assessment")):
        issues.append("data_loss_assessment_invalid")
    if record.get("rollback_authorized") is not False:
        issues.append("rollback_authorization_must_be_false")
    if record.get("rollback_executed") is not False:
        issues.append("rollback_execution_must_be_false")
    if record.get("production_change") is not False:
        issues.append("production_change_must_be_false")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
        "guardrails_verified": False, "rollback_readiness_verified": False,
    }


def stage_590_stop_rollback_gate(record):
    result = validate_stop_rollback(record)
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "REVIEW_REQUIRED",
        "automatic_stop_action": False,
        "automatic_rollback": False,
        "automatic_resume": False,
    }
