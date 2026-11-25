import pytest

from core.self_improvement_measurement import SelfImprovementMeasurementRecord
from scripts import rsi_measurement_evidence_adapter as adapter


BASE = "a" * 40
PRODUCED = "b" * 40
TASK = "task-42"
NONCE = "c" * 32


def loop_row(**changes):
    row = {
        "base_sha": BASE,
        "produced_sha": PRODUCED,
        "task_id": TASK,
        "run_nonce": NONCE,
        "test_evidence": ["ci-run-123"],
    }
    row.update(changes)
    return row


def metric_snapshot(sha, value, **changes):
    snapshot = {
        "schema_version": 1,
        "metric_name": "test_pass_rate",
        "metric_direction": "maximize",
        "value": value,
        "sample_count": 10,
        "target_sha": sha,
        "task_id": TASK,
        "run_nonce": NONCE,
        "evidence_id": "metric-artifact-1",
    }
    snapshot.update(changes)
    return snapshot


def test_verified_evidence_produces_bound_measurement(monkeypatch):
    monkeypatch.setattr(adapter, "publish_row_has_valid_gates", lambda row, *, expected_sha: expected_sha == BASE)
    record, reason = adapter.verify_rsi_measurement_evidence(
        loop_row(),
        metric_snapshot(BASE, 0.8),
        metric_snapshot(PRODUCED, 0.9, evidence_id="metric-artifact-2"),
    )
    assert reason == "metric_artifact_attestation_missing"
    assert isinstance(record, SelfImprovementMeasurementRecord)
    assert record.verdict == "INSUFFICIENT_EVIDENCE"
    assert record.base_sha == BASE
    assert record.produced_sha == PRODUCED
    assert record.test_evidence == ("ci-run-123",)
    assert record.to_record()["execution_authorized"] is False
    assert record.to_record()["safety_gate"] == "UNKNOWN"


def test_missing_or_failed_safety_gate_fails_closed(monkeypatch):
    monkeypatch.setattr(adapter, "publish_row_has_valid_gates", lambda row, *, expected_sha: False)
    record, reason = adapter.verify_rsi_measurement_evidence(
        loop_row(), metric_snapshot(BASE, 0.8), metric_snapshot(PRODUCED, 0.9)
    )
    assert record is None
    assert reason == "loop_safety_gates_not_verified"


@pytest.mark.parametrize(
    "baseline,candidate,expected_reason",
    [
        (metric_snapshot("d" * 40, 0.8), metric_snapshot(PRODUCED, 0.9), "baseline_metric_evidence_invalid"),
        (metric_snapshot(BASE, 0.8), metric_snapshot("d" * 40, 0.9), "candidate_metric_evidence_invalid"),
        (metric_snapshot(BASE, 0.8), metric_snapshot(PRODUCED, 0.9, metric_name="latency"), "metric_definition_mismatch"),
        (metric_snapshot(BASE, 0.8, sample_count=0), metric_snapshot(PRODUCED, 0.9), "baseline_metric_evidence_invalid"),
        (metric_snapshot(BASE, float("nan")), metric_snapshot(PRODUCED, 0.9), "baseline_metric_evidence_invalid"),
    ],
)
def test_mismatched_or_invalid_metric_evidence_is_rejected(monkeypatch, baseline, candidate, expected_reason):
    monkeypatch.setattr(adapter, "publish_row_has_valid_gates", lambda row, *, expected_sha: True)
    record, reason = adapter.verify_rsi_measurement_evidence(loop_row(), baseline, candidate)
    assert record is None
    assert reason == expected_reason


def test_missing_test_evidence_is_not_promoted_to_improvement(monkeypatch):
    monkeypatch.setattr(adapter, "publish_row_has_valid_gates", lambda row, *, expected_sha: True)
    record, reason = adapter.verify_rsi_measurement_evidence(
        loop_row(test_evidence=[]),
        metric_snapshot(BASE, 0.8),
        metric_snapshot(PRODUCED, 0.9),
    )
    assert record is None
    assert reason == "test_evidence_missing_or_invalid"


def test_provenance_mismatch_is_rejected_before_gate_call(monkeypatch):
    called = []
    monkeypatch.setattr(adapter, "publish_row_has_valid_gates", lambda *args, **kwargs: called.append(True))
    record, reason = adapter.verify_rsi_measurement_evidence(
        loop_row(run_nonce="not-a-nonce"),
        metric_snapshot(BASE, 0.8),
        metric_snapshot(PRODUCED, 0.9),
    )
    assert record is None
    assert reason == "loop_provenance_invalid"
    assert called == []
