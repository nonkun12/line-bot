import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage586", Path(__file__).parents[1] / "core/ai_factory_stage586_590_stop_rollback_integrity.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "stop_conditions": ["guardrail breach", "evidence invalid"],
        "triggered_stop_conditions": [],
        "guardrail_checks": [{"id": "quality", "status": "PASS"},
                             {"id": "safety", "status": "PASS"}],
        "rollback_plan_ref": "rollback-plan-1", "rollback_scope": "candidate-only",
        "data_loss_assessment": "no persistent data writes are in scope",
        "rollback_authorized": False, "rollback_executed": False,
        "production_change": False,
    }


def test_complete_declarations_still_require_review():
    result = m.stage_590_stop_rollback_gate(good())
    assert result["status"] == "DECLARATIONS_COMPLETE"
    assert result["gate"] == "REVIEW_REQUIRED"
    assert result["guardrails_verified"] is False
    assert result["automatic_rollback"] is False
    assert result["automatic_resume"] is False


def test_triggered_stop_condition_blocks():
    record = good()
    record["triggered_stop_conditions"] = ["safety threshold exceeded"]
    assert m.validate_stop_rollback(record)["status"] == "BLOCKED"


def test_failed_or_unknown_guardrail_blocks():
    for status in ("FAIL", "UNKNOWN"):
        record = good()
        record["guardrail_checks"][0]["status"] = status
        assert m.validate_stop_rollback(record)["status"] == "BLOCKED"


def test_duplicate_guardrail_identity_blocks():
    record = good()
    record["guardrail_checks"].append({"id": "quality", "status": "PASS"})
    assert m.validate_stop_rollback(record)["status"] == "BLOCKED"


def test_rollback_authorization_or_execution_blocks():
    for field in ("rollback_authorized", "rollback_executed", "production_change"):
        record = good()
        record[field] = True
        assert m.validate_stop_rollback(record)["status"] == "BLOCKED"


def test_missing_rollback_scope_and_empty_stop_policy_block():
    record = good()
    record["rollback_scope"] = ""
    record["stop_conditions"] = []
    assert m.validate_stop_rollback(record)["status"] == "BLOCKED"
