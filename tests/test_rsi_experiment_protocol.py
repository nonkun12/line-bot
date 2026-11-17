"""Regression tests for the read-only RSI comparison protocol."""
from __future__ import annotations

from copy import deepcopy

from core.rsi_experiment_protocol import evaluate_comparison


def _record():
    return {
        "experiment_id": "rsi-smoke-001",
        "baseline": {
            "candidate_id": "baseline-v1",
            "artifact_sha256": "a" * 64,
            "score": 0.70,
        },
        "challenger": {
            "candidate_id": "challenger-v1",
            "artifact_sha256": "b" * 64,
            "score": 0.76,
        },
        "evaluator": {
            "evaluator_id": "independent-evaluator-v1",
            "version": "1",
            "metric": "held_out_accuracy",
            "direction": "higher",
            "minimum_delta": 0.02,
        },
        "held_out": {
            "dataset_id": "heldout-v1",
            "dataset_sha256": "c" * 64,
            "sample_count": 100,
            "locked": True,
        },
        "safety": {
            "stop_state": "INACTIVE",
            "global_hold_state": "CLEAR",
        },
    }


def test_challenger_pass_is_comparison_only_and_grants_no_authority():
    result = evaluate_comparison(_record())

    assert result["status"] == "PASS"
    assert result["improvement"] == 0.06
    assert result["execution_authorized"] is False
    assert result["patch_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["stop_clear_authorized"] is False
    assert result["merge_deploy_authorized"] is False
    assert result["required_human_approval"] is True


def test_no_positive_improvement_fails():
    record = _record()
    record["challenger"]["score"] = record["baseline"]["score"]

    assert evaluate_comparison(record)["status"] == "FAIL"


def test_lower_is_better_metric_uses_inverse_delta():
    record = _record()
    record["evaluator"]["direction"] = "lower"
    record["baseline"]["score"] = 0.30
    record["challenger"]["score"] = 0.20

    result = evaluate_comparison(record)
    assert result["status"] == "PASS"
    assert result["improvement"] == 0.1


def test_active_or_unverified_stop_blocks_evaluation():
    for state in ("ACTIVE", "UNKNOWN", None):
        record = _record()
        record["safety"]["stop_state"] = state
        result = evaluate_comparison(record)
        assert result["status"] == "BLOCKED"
        assert result["execution_authorized"] is False


def test_global_hold_blocks_evaluation_without_clearing_hold():
    record = _record()
    record["safety"]["global_hold_state"] = "ACTIVE"

    result = evaluate_comparison(record)
    assert result["status"] == "BLOCKED"
    assert result["hold_clear_authorized"] is False


def test_evaluator_must_be_independent_from_both_candidates():
    record = _record()
    record["evaluator"]["evaluator_id"] = record["challenger"]["candidate_id"]

    assert evaluate_comparison(record)["reason"] == "evaluator_must_be_independent"


def test_unlocked_or_invalid_holdout_is_blocked():
    record = _record()
    record["held_out"]["locked"] = False

    assert evaluate_comparison(record)["status"] == "BLOCKED"


def test_boolean_score_is_not_accepted_as_numeric():
    record = _record()
    record["challenger"]["score"] = True

    assert evaluate_comparison(record)["status"] == "BLOCKED"


def test_input_record_is_not_mutated():
    record = _record()
    original = deepcopy(record)

    evaluate_comparison(record)

    assert record == original


def test_evidence_digest_is_stable_for_same_record():
    record = _record()

    first = evaluate_comparison(record)
    second = evaluate_comparison(record)

    assert first["evidence_sha256"] == second["evidence_sha256"]
