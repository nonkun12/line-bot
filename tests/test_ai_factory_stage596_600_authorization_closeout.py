import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage596", Path(__file__).parents[1] / "core/ai_factory_stage596_600_authorization_closeout.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "authorization_ref": "auth-1", "authorization_owner_ref": "owner-1",
        "authorization_scope": "offline-validation-only",
        "authorization_status": "GRANTED_DECLARED",
        "authorization_expires_at": "2026-12-01T00:00:00Z",
        "authorization_revoked": False,
        "residual_risks": ["metric provenance is caller-declared"],
        "unresolved_issues": [],
        "audit_record_ref": "audit-1", "closeout_owner_ref": "closeout-owner-1",
        "closeout_status": "CLOSED_WITH_FOLLOW_UP",
        "automatic_execution": False, "production_change": False, "model_change": False,
    }


def test_complete_declarations_only_ready_for_independent_review():
    result = m.stage_600_authorization_closeout_gate(
        good(), now=datetime(2026, 11, 24, tzinfo=timezone.utc)
    )
    assert result["status"] == "DECLARATIONS_COMPLETE"
    assert result["gate"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert result["authorization_authenticity_verified"] is False
    assert result["execution_authorized"] is False
    assert result["automatic_release"] is False


def test_missing_or_expired_authorization_blocks():
    record = good()
    record["authorization_ref"] = ""
    assert m.validate_authorization_closeout(record)["status"] == "BLOCKED"
    record = good()
    result = m.validate_authorization_closeout(
        record, now=datetime(2026, 12, 2, tzinfo=timezone.utc)
    )
    assert "authorization_expired" in result["issues"]


def test_revocation_and_unknown_authorization_block():
    for field, value in (("authorization_revoked", True),
                         ("authorization_status", "UNKNOWN")):
        record = good()
        record[field] = value
        assert m.validate_authorization_closeout(record)["status"] == "BLOCKED"


def test_scope_audit_and_risk_records_required():
    for field, value in (("authorization_scope", ""),
                         ("audit_record_ref", ""),
                         ("residual_risks", [])):
        record = good()
        record[field] = value
        assert m.validate_authorization_closeout(record)["status"] == "BLOCKED"


def test_unsafe_actions_and_bad_closeout_block():
    for field, value in (("automatic_execution", True),
                         ("production_change", True),
                         ("model_change", True),
                         ("closeout_status", "DONE")):
        record = good()
        record[field] = value
        assert m.validate_authorization_closeout(record)["status"] == "BLOCKED"


def test_unresolved_issues_must_be_explicit_text_list():
    record = good()
    record["unresolved_issues"] = [""]
    assert m.validate_authorization_closeout(record)["status"] == "BLOCKED"
