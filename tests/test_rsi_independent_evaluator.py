"""Tests for the independent deterministic RSI evaluator."""
from __future__ import annotations

import hashlib
import json

from core.rsi_independent_evaluator import evaluate_exact_match


def _kwargs():
    dataset = [
        {"sample_id": "s1", "expected": "alpha"},
        {"sample_id": "s2", "expected": "beta"},
        {"sample_id": "s3", "expected": "gamma"},
        {"sample_id": "s4", "expected": "delta"},
    ]
    return {
        "experiment_id": "rsi-exact-match-001",
        "dataset": dataset,
        "baseline_predictions": [
            {"sample_id": "s1", "output": "alpha"},
            {"sample_id": "s2", "output": "wrong"},
            {"sample_id": "s3", "output": "gamma"},
            {"sample_id": "s4", "output": "wrong"},
        ],
        "challenger_predictions": [
            {"sample_id": "s1", "output": "alpha"},
            {"sample_id": "s2", "output": "beta"},
            {"sample_id": "s3", "output": "gamma"},
            {"sample_id": "s4", "output": "delta"},
        ],
        "baseline_candidate_id": "baseline-v1",
        "baseline_artifact_sha256": "a" * 64,
        "challenger_candidate_id": "challenger-v1",
        "challenger_artifact_sha256": "b" * 64,
        "evaluator_id": "independent-exact-match-v1",
        "evaluator_version": "1",
        "minimum_delta": 0.2,
        "safety": {"stop_state": "INACTIVE", "global_hold_state": "CLEAR"},
        "held_out_locked": True,
        "held_out_expected_sha256": hashlib.sha256(
            json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest(),
    }


def test_evaluator_recomputes_scores_from_locked_fixture_outputs():
    result = evaluate_exact_match(**_kwargs())

    assert result["result"]["status"] == "PASS"
    assert result["baseline_correct"] == 2
    assert result["challenger_correct"] == 4
    assert result["record"]["baseline"]["score"] == 0.5
    assert result["record"]["challenger"]["score"] == 1.0
    assert result["record"]["held_out"]["sample_count"] == 4
    assert result["record"]["held_out"]["locked"] is True
    assert result["result"]["execution_authorized"] is False


def test_missing_prediction_is_blocked_not_scored():
    args = _kwargs()
    args["challenger_predictions"] = args["challenger_predictions"][:-1]

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "prediction_coverage_mismatch"


def test_duplicate_held_out_sample_id_is_blocked():
    args = _kwargs()
    args["dataset"].append({"sample_id": "s1", "expected": "alpha"})

    import hashlib
    import json
    args["held_out_expected_sha256"] = hashlib.sha256(
        json.dumps(args["dataset"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "held_out_sample_id_duplicate"


def test_duplicate_prediction_id_is_blocked():
    args = _kwargs()
    args["challenger_predictions"].append(args["challenger_predictions"][0])

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "prediction_sample_id_duplicate"


def test_unicode_nfc_equivalent_outputs_match():
    args = _kwargs()
    args["dataset"] = [{"sample_id": "s1", "expected": "café"}]
    args["baseline_predictions"] = [{"sample_id": "s1", "output": "cafe\u0301"}]
    args["challenger_predictions"] = [{"sample_id": "s1", "output": "café"}]
    args["held_out_expected_sha256"] = hashlib.sha256(
        json.dumps(args["dataset"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()

    result = evaluate_exact_match(**args)

    assert result["baseline_correct"] == 1
    assert result["challenger_correct"] == 1


def test_active_stop_blocks_even_when_challenger_scores_higher():
    args = _kwargs()
    args["safety"]["stop_state"] = "ACTIVE"

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["execution_authorized"] is False


def test_non_string_candidate_output_is_blocked():
    args = _kwargs()
    args["challenger_predictions"][0]["output"] = {"text": "alpha"}

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "prediction_output_must_be_string"

def test_unattested_held_out_fixture_is_blocked():
    args = _kwargs()
    args["held_out_locked"] = False

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "held_out_fixture_lock_not_attested"


def test_candidate_prediction_outputs_are_hash_bound():
    result = evaluate_exact_match(**_kwargs())

    baseline = result["record"]["baseline"]["predictions_sha256"]
    challenger = result["record"]["challenger"]["predictions_sha256"]
    assert len(baseline) == 64
    assert len(challenger) == 64
    assert baseline != challenger

def test_held_out_manifest_digest_mismatch_is_blocked():
    args = _kwargs()
    args["held_out_expected_sha256"] = "f" * 64

    result = evaluate_exact_match(**args)

    assert result["result"]["status"] == "BLOCKED"
    assert result["result"]["reason"] == "held_out_manifest_digest_mismatch"
