import pytest

from core.self_improvement_history import SelfImprovementHistory
from core.self_improvement_measurement import SelfImprovementMeasurementRecord
from scripts.self_improvement_state import sanitize_records, validate_durable_history


BASE = "a" * 40
PRODUCED = "b" * 40


def measurement(**changes):
    values = {
        "proposal_id": "proposal-1",
        "metric_name": "test_pass_rate",
        "metric_direction": "maximize",
        "baseline": 0.8,
        "candidate": 0.9,
        "base_sha": BASE,
        "produced_sha": PRODUCED,
        "test_evidence": ("ci-run-123",),
        "safety_gate": "PASS",
    }
    values.update(changes)
    return SelfImprovementMeasurementRecord(**values)


def test_measurement_verdicts_require_sha_test_and_safety_evidence():
    assert measurement().verdict == "IMPROVED"
    assert measurement(candidate=0.8).verdict == "NO_CHANGE"
    assert measurement(candidate=0.7).verdict == "REGRESSION"
    assert measurement(base_sha="").verdict == "INSUFFICIENT_EVIDENCE"
    assert measurement(test_evidence=()).verdict == "INSUFFICIENT_EVIDENCE"
    assert measurement(safety_gate="UNKNOWN").verdict == "INSUFFICIENT_EVIDENCE"
    assert measurement(safety_gate="FAIL").verdict == "REGRESSION"


def test_minimize_metric_uses_lower_candidate_as_improvement():
    assert measurement(metric_direction="minimize", baseline=10, candidate=8).verdict == "IMPROVED"


@pytest.mark.parametrize("changes", [
    {"proposal_id": "../bad"},
    {"metric_direction": "auto"},
    {"baseline": float("nan")},
    {"candidate": float("inf")},
    {"base_sha": "not-a-sha"},
    {"produced_sha": "A" * 40},
    {"test_evidence": ("raw traceback text with spaces",)},
    {"safety_gate": "APPROVED"},
])
def test_measurement_rejects_malformed_or_unsafe_fields(changes):
    with pytest.raises(ValueError):
        measurement(**changes)


def test_measurement_identity_is_deterministic_and_binds_evidence():
    first = measurement()
    assert first.measurement_id == measurement().measurement_id
    assert first.measurement_id != measurement(test_evidence=("ci-run-124",)).measurement_id


def test_history_round_trip_deduplicates_and_preserves_execution_lock(tmp_path):
    store = SelfImprovementHistory(tmp_path / "history.jsonl")
    record = measurement()
    store.append_measurement(record)
    store.append_measurement(record)
    assert store.load_measurements() == (record,)
    raw = (tmp_path / "history.jsonl").read_text(encoding="utf-8")
    assert '"execution_authorized": false' in raw


def test_state_sanitizer_and_durable_validator_keep_only_valid_measurements():
    valid = measurement().to_record()
    invalid = {**valid, "verdict": "IMPROVED", "execution_authorized": True}
    safe = sanitize_records([valid, invalid])
    assert safe == [valid]
    assert validate_durable_history(safe) == [valid]
    with pytest.raises(ValueError, match="measurement"):
        validate_durable_history([invalid])


def test_incomplete_measurement_is_preserved_as_insufficient_not_promoted():
    record = measurement(base_sha="", test_evidence=()).to_record()
    assert record["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert sanitize_records([record]) == [record]
