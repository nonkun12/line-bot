from __future__ import annotations

import pytest

from core.idea_hypothesis import ExperimentHypothesis, classify_observation


def valid_hypothesis(**overrides):
    values = {
        "hypothesis_id": "latency-cache-v1",
        "statement": "A bounded cache reduces repeated lookup latency.",
        "prediction": "p95 latency falls by at least 20 percent.",
        "metric": "p95 latency in milliseconds",
        "direction": "decrease",
        "baseline": 100.0,
        "success_threshold": 80.0,
        "failure_threshold": 95.0,
        "baseline_source": "Fixed 100-request baseline run, commit abc123.",
        "measurement_method": "Same hardware, dataset, and load; report p50 and p95.",
        "evidence_requirements": ("raw latency samples", "commit SHA and environment"),
        "reproducibility_steps": ("run baseline command", "run candidate command"),
    }
    values.update(overrides)
    return ExperimentHypothesis(**values)


def test_accepts_falsifiable_hypothesis_with_provenance_and_reproduction():
    hypothesis = valid_hypothesis()
    assert hypothesis.direction == "decrease"
    assert hypothesis.baseline_source.startswith("Fixed")
    assert len(hypothesis.evidence_requirements) == 2
    assert len(hypothesis.reproducibility_steps) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"direction": "better"},
        {"direction": "increase", "success_threshold": 90.0, "failure_threshold": 95.0},
        {"direction": "decrease", "success_threshold": 100.0, "failure_threshold": 95.0},
        {"direction": "decrease", "baseline": 70.0},
        {"baseline": float("nan")},
        {"success_threshold": float("inf")},
        {"failure_threshold": True},
        {"baseline_source": " "},
        {"measurement_method": ""},
        {"evidence_requirements": ()},
        {"reproducibility_steps": (" ",)},
        {"evidence_requirements": tuple(f"e{i}" for i in range(9))},
        {"reproducibility_steps": ("x" * 301,)},
    ],
)
def test_rejects_invalid_or_unbounded_contracts(overrides):
    with pytest.raises(ValueError):
        valid_hypothesis(**overrides)


def test_contract_does_not_grant_execution_or_approval():
    hypothesis = valid_hypothesis()
    assert not hasattr(hypothesis, "execute")
    assert not hasattr(hypothesis, "approval_granted")



def test_classifies_observations_using_predeclared_thresholds():
    hypothesis = valid_hypothesis()
    assert classify_observation(hypothesis, 79.9) == "success"
    assert classify_observation(hypothesis, 80.0) == "success"
    assert classify_observation(hypothesis, 95.0) == "failure"
    assert classify_observation(hypothesis, 90.0) == "unverified"


def test_classifies_increase_direction_and_rejects_invalid_measurements():
    hypothesis = valid_hypothesis(
        direction="increase",
        baseline=10.0,
        success_threshold=15.0,
        failure_threshold=5.0,
    )
    assert classify_observation(hypothesis, 15.0) == "success"
    assert classify_observation(hypothesis, 5.0) == "failure"
    assert classify_observation(hypothesis, 12.0) == "unverified"
    with pytest.raises(ValueError):
        classify_observation(hypothesis, float("inf"))
    with pytest.raises(ValueError):
        classify_observation(hypothesis, True)
