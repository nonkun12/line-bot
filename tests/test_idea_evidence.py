from __future__ import annotations

import pytest

from core.idea_evidence import (
    ExperimentEvidence,
    build_verified_idea_outcomes,
    classify_measurement,
)
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_learning import rank_idea_styles


@pytest.fixture
def hypothesis():
    return ExperimentHypothesis(
        hypothesis_id="latency-v1",
        statement="Caching reduces p95 latency.",
        prediction="p95 falls below 80ms.",
        metric="p95 latency ms",
        direction="decrease",
        baseline=100.0,
        success_threshold=80.0,
        failure_threshold=95.0,
        baseline_source="Baseline benchmark run b-001.",
        measurement_method="Same workload and hardware.",
        evidence_requirements=("raw samples", "environment manifest"),
        reproducibility_steps=("run baseline", "run candidate"),
    )


def record(**overrides):
    values = {
        "experiment_id": "exp-001",
        "hypothesis_id": "latency-v1",
        "style": "recombine",
        "measured_value": 75.0,
        "evidence_refs": ("artifact:sha256:abc",),
        "code_revision": "a" * 40,
        "environment": "python=3.x; runner=linux",
        "verification_status": "verified",
        "verified_by": "independent-review-17",
    }
    values.update(overrides)
    return ExperimentEvidence(**values)


def test_classifies_success_failure_and_gray_zone(hypothesis):
    assert classify_measurement(hypothesis, 75.0) == "success"
    assert classify_measurement(hypothesis, 99.0) == "failure"
    assert classify_measurement(hypothesis, 90.0) == "unverified"


def test_only_independently_verified_records_become_learning_signals(hypothesis):
    outcomes = build_verified_idea_outcomes(
        hypothesis,
        (
            record(),
            record(experiment_id="exp-002", measured_value=99.0),
            record(experiment_id="exp-003", verification_status="pending", verified_by=""),
            record(experiment_id="exp-004", verification_status="rejected", verified_by=""),
            record(experiment_id="exp-005", measured_value=90.0),
        ),
    )
    assert [item.result for item in outcomes] == [
        "success", "failure", "unverified", "unverified", "unverified"
    ]
    assert "artifact:sha256:abc" in outcomes[0].evidence
    assert "rev=" in outcomes[0].evidence
    assert "env=" in outcomes[0].evidence


def test_unverified_records_do_not_change_learning_ranking(hypothesis):
    baseline = rank_idea_styles(("reframe", "recombine", "specialize"))
    outcomes = build_verified_idea_outcomes(
        hypothesis,
        (record(verification_status="pending", verified_by=""),),
    )
    assert rank_idea_styles(("reframe", "recombine", "specialize"), outcomes) == baseline


def test_rejects_missing_provenance_or_unverified_reviewer(hypothesis):
    with pytest.raises(ValueError):
        record(evidence_refs=())
    with pytest.raises(ValueError):
        record(verification_status="verified", verified_by="")
    with pytest.raises(ValueError):
        record(verification_status="pending", verified_by="someone")


def test_rejects_duplicate_or_mismatched_experiment_records(hypothesis):
    with pytest.raises(ValueError, match="duplicate"):
        build_verified_idea_outcomes(hypothesis, (record(), record()))
    with pytest.raises(ValueError, match="does not match"):
        build_verified_idea_outcomes(hypothesis, (record(hypothesis_id="other"),))


def test_rejects_non_finite_measurements():
    with pytest.raises(ValueError):
        record(measured_value=float("nan"))
