import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage591", Path(__file__).parents[1] / "core/ai_factory_stage591_595_decision_governance.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "decision_id": "decision-1", "candidate_ref": "candidate-1",
        "evidence_refs": ["evidence-1", "evidence-2"],
        "decision_basis": ["benchmark result", "regression guardrail"],
        "disposition": "ACCEPT_FOR_FURTHER_TESTING",
        "decision_scope": "offline evaluation only", "decision_owner_ref": "owner-1",
        "decided_at": "2026-11-23T10:00:00Z", "valid_until": "2026-12-01T10:00:00Z",
        "dissent_records": [], "revalidation_triggers": ["new model revision"],
        "automatic_execution": False, "production_change": False, "model_change": False,
    }


def test_complete_decision_requires_authorization():
    result = m.stage_595_decision_governance_gate(
        good(), now=datetime(2026, 11, 24, tzinfo=timezone.utc)
    )
    assert result["status"] == "DECISION_DECLARATION_COMPLETE"
    assert result["gate"] == "AUTHORIZATION_REQUIRED"
    assert result["decision_authenticity_verified"] is False
    assert result["automatic_release"] is False


def test_expired_decision_blocks():
    record = good()
    record["valid_until"] = "2026-11-23T10:00:00Z"
    result = m.validate_candidate_decision(
        record, now=datetime(2026, 11, 24, tzinfo=timezone.utc)
    )
    assert "decision_expired" in result["issues"]


def test_invalid_disposition_and_duplicate_evidence_block():
    record = good()
    record["disposition"] = "SHIP_NOW"
    record["evidence_refs"] = ["same", "same"]
    assert m.validate_candidate_decision(record)["status"] == "BLOCKED"


def test_naive_or_reversed_timestamps_block():
    record = good()
    record["decided_at"] = "2026-11-23T10:00:00"
    assert m.validate_candidate_decision(record)["status"] == "BLOCKED"
    record = good()
    record["valid_until"] = "2026-11-22T10:00:00Z"
    assert m.validate_candidate_decision(record)["status"] == "BLOCKED"


def test_automatic_actions_and_mutations_block():
    for field in ("automatic_execution", "production_change", "model_change"):
        record = good()
        record[field] = True
        assert m.validate_candidate_decision(record)["status"] == "BLOCKED"


def test_dissent_and_revalidation_fields_are_validated():
    record = good()
    record["dissent_records"] = [""]
    assert m.validate_candidate_decision(record)["status"] == "BLOCKED"
    record = good()
    record["revalidation_triggers"] = []
    assert m.validate_candidate_decision(record)["status"] == "BLOCKED"
