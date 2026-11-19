from __future__ import annotations

from dataclasses import replace

import pytest

from core.idea_evidence import (
    ExperimentEvidence,
    build_verified_idea_outcomes,
    classify_measurement,
    sign_evidence_record,
)
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_learning import rank_idea_styles

REVIEWER_KEY = b"unit-test-reviewer-key-material-32-bytes-minimum"


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
        "verification_status": "pending",
    }
    values.update(overrides)
    if values["verification_status"] == "verified":
        values.setdefault("verified_by", "independent-review-17")
    item = ExperimentEvidence(**values)
    if item.verification_status == "verified":
        item = replace(
            item,
            verification_signature=sign_evidence_record(item, REVIEWER_KEY),
        )
    return item


def test_classifies_success_failure_and_gray_zone(hypothesis):
    assert classify_measurement(hypothesis, 75.0) == "success"
    assert classify_measurement(hypothesis, 99.0) == "failure"
    assert classify_measurement(hypothesis, 90.0) == "unverified"


def test_only_signed_independently_verified_records_become_learning_signals(hypothesis):
    outcomes = build_verified_idea_outcomes(
        hypothesis,
        (
            record(verification_status="verified"),
            record(experiment_id="exp-002", measured_value=99.0, verification_status="verified"),
            record(experiment_id="exp-003", verification_status="pending"),
            record(experiment_id="exp-004", verification_status="rejected"),
            record(experiment_id="exp-005", measured_value=90.0, verification_status="verified"),
        ),
        reviewer_keys={"independent-review-17": REVIEWER_KEY},
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
        (record(verification_status="pending"),),
        reviewer_keys={},
    )
    assert rank_idea_styles(("reframe", "recombine", "specialize"), outcomes) == baseline


def test_rejects_missing_provenance_or_unverified_reviewer(hypothesis):
    with pytest.raises(ValueError):
        record(evidence_refs=())
    with pytest.raises(ValueError):
        ExperimentEvidence(
            experiment_id="missing-reviewer",
            hypothesis_id="latency-v1",
            style="recombine",
            measured_value=75.0,
            evidence_refs=("artifact:1",),
            code_revision="a" * 40,
            environment="python=3.x",
            verification_status="verified",
        )


def test_rejects_forged_or_unknown_reviewer_attestations(hypothesis):
    forged = record(verification_status="verified")
    with pytest.raises(ValueError, match="invalid evidence attestation"):
        build_verified_idea_outcomes(
            hypothesis,
            (replace(forged, measured_value=70.0),),
            reviewer_keys={"independent-review-17": REVIEWER_KEY},
        )
    with pytest.raises(ValueError, match="no trusted reviewer key"):
        build_verified_idea_outcomes(
            hypothesis,
            (forged,),
            reviewer_keys={},
        )


def test_rejects_duplicate_or_mismatched_experiment_records(hypothesis):
    with pytest.raises(ValueError, match="duplicate"):
        build_verified_idea_outcomes(
            hypothesis, (record(), record()), reviewer_keys={}
        )
    with pytest.raises(ValueError, match="does not match"):
        build_verified_idea_outcomes(
            hypothesis,
            (record(hypothesis_id="other"),),
            reviewer_keys={},
        )


def test_rejects_non_finite_measurements():
    with pytest.raises(ValueError):
        record(measured_value=float("nan"))


def test_idea_agent_end_to_end_uses_only_verified_evidence(hypothesis):
    from core.idea_ai import IdeaAgent

    records = tuple(
        record(experiment_id=f"success-{i}", style="recombine", verification_status="verified")
        for i in range(20)
    ) + tuple(
        record(
            experiment_id=f"failure-{i}",
            style="reframe",
            measured_value=99.0,
            verification_status="verified",
        )
        for i in range(20)
    ) + (
        record(
            experiment_id="pending-001",
            style="specialize",
            verification_status="pending",
        ),
    )
    ideas = IdeaAgent().propose_from_evidence(
        "improve autonomous reasoning",
        hypothesis,
        records,
        limit=5,
        reviewer_keys={"independent-review-17": REVIEWER_KEY},
    )
    assert len(ideas) == 5
    styles = [idea.style for idea in ideas]
    assert styles.index("recombine") < styles.index("reframe")
    assert all("No implementation, execution, merge, deploy" in idea.task.instruction for idea in ideas)
