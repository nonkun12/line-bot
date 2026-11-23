import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage581", Path(__file__).parents[1] / "core/ai_factory_stage581_585_evaluation_integrity.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "evaluator_ref": "evaluator-1", "evaluation_run_ref": "run-1",
        "subject_ref": "candidate-1", "rubric_ref": "rubric-1",
        "result_ref": "result-1", "evaluated_at": "2026-11-23T10:00:00Z",
        "metric_results": [{"metric": "accuracy", "value": 0.91, "unit": "ratio"}],
        "limitations": ["small sample"], "conflict_declaration": [],
        "evaluator_independent": True, "production_change": False, "model_change": False,
    }


def test_complete_evidence_still_requires_review():
    result = m.stage_585_evaluation_integrity_gate(good())
    assert result["status"] == "EVIDENCE_COMPLETE"
    assert result["gate"] == "REVIEW_REQUIRED"
    assert result["result_integrity_verified"] is False
    assert result["automatic_acceptance"] is False


def test_missing_provenance_blocks():
    record = good()
    record["rubric_ref"] = ""
    assert m.validate_evaluation_integrity(record)["status"] == "BLOCKED"


def test_duplicate_metric_identity_blocks():
    record = good()
    record["metric_results"].append({"metric": "accuracy", "value": 0.92, "unit": "ratio"})
    assert "metric_results_1_identity_invalid" in m.validate_evaluation_integrity(record)["issues"]


def test_nonfinite_and_boolean_values_block():
    for value in (float("nan"), float("inf"), True):
        record = good()
        record["metric_results"][0]["value"] = value
        assert m.validate_evaluation_integrity(record)["status"] == "BLOCKED"


def test_evaluator_conflict_or_mutation_blocks():
    record = good()
    record["evaluator_independent"] = False
    assert m.validate_evaluation_integrity(record)["status"] == "BLOCKED"
    record = good()
    record["model_change"] = True
    assert m.validate_evaluation_integrity(record)["status"] == "BLOCKED"


def test_invalid_timestamp_and_empty_limitations_block():
    record = good()
    record["evaluated_at"] = "yesterday"
    record["limitations"] = []
    assert m.validate_evaluation_integrity(record)["status"] == "BLOCKED"
