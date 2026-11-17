"""Independent deterministic evaluator for locked RSI held-out fixtures.

The evaluator scores candidate outputs against caller-attested locked expected outputs.
It does not invoke a model, execute candidate code, access the network, or
change repository files. It supports exact-match fixtures only; subjective
quality metrics require a separately reviewed evaluator implementation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from core.rsi_experiment_protocol import evaluate_comparison

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVALUATOR_ID = "rsi.exact_match.v1"
EVALUATOR_VERSION = "1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalize_output(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("prediction_output_must_be_string")
    return unicodedata.normalize("NFC", value)


def _score(
    samples: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> tuple[float, int]:
    expected_ids = [sample.get("sample_id") for sample in samples]
    predicted_ids = [prediction.get("sample_id") for prediction in predictions]
    if any(not isinstance(item, str) or not item for item in expected_ids + predicted_ids):
        raise ValueError("sample_id_invalid")
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError("held_out_sample_id_duplicate")
    if len(set(predicted_ids)) != len(predicted_ids):
        raise ValueError("prediction_sample_id_duplicate")
    if set(expected_ids) != set(predicted_ids):
        raise ValueError("prediction_coverage_mismatch")

    prediction_map = {item["sample_id"]: item for item in predictions}
    correct = 0
    for sample in samples:
        expected = _normalize_output(sample.get("expected"))
        actual = _normalize_output(prediction_map[sample["sample_id"]].get("output"))
        correct += expected == actual
    return correct / len(samples), correct


def evaluate_exact_match(
    *,
    experiment_id: str,
    dataset: Sequence[Mapping[str, Any]],
    baseline_predictions: Sequence[Mapping[str, Any]],
    challenger_predictions: Sequence[Mapping[str, Any]],
    baseline_candidate_id: str,
    baseline_artifact_sha256: str,
    challenger_candidate_id: str,
    challenger_artifact_sha256: str,
    evaluator_id: str,
    evaluator_version: str,
    minimum_delta: float,
    safety: Mapping[str, Any],
    held_out_locked: bool,
    held_out_expected_sha256: str,
) -> dict[str, Any]:
    """Build and evaluate an exact-match comparison from actual held-out rows."""
    try:
        if held_out_locked is not True:
            raise ValueError("held_out_fixture_lock_not_attested")
        if evaluator_id != EVALUATOR_ID or evaluator_version != EVALUATOR_VERSION:
            raise ValueError("evaluator_identity_mismatch")
        if isinstance(dataset, (str, bytes)) or not isinstance(dataset, Sequence) or not dataset:
            raise ValueError("held_out_dataset_empty_or_invalid")
        if not all(isinstance(row, Mapping) and "sample_id" in row and "expected" in row for row in dataset):
            raise ValueError("held_out_dataset_row_invalid")
        if not isinstance(baseline_predictions, Sequence) or isinstance(baseline_predictions, (str, bytes)):
            raise ValueError("baseline_predictions_invalid")
        if not isinstance(challenger_predictions, Sequence) or isinstance(challenger_predictions, (str, bytes)):
            raise ValueError("challenger_predictions_invalid")
        if not all(isinstance(row, Mapping) for row in baseline_predictions):
            raise ValueError("baseline_prediction_row_invalid")
        if not all(isinstance(row, Mapping) for row in challenger_predictions):
            raise ValueError("challenger_prediction_row_invalid")
        if not _SHA256.fullmatch(baseline_artifact_sha256) or not _SHA256.fullmatch(challenger_artifact_sha256):
            raise ValueError("candidate_artifact_digest_invalid")
        if not math.isfinite(float(minimum_delta)) or minimum_delta < 0:
            raise ValueError("minimum_delta_invalid")

        dataset_rows = [dict(row) for row in dataset]
        dataset_sha256 = hashlib.sha256(_canonical(dataset_rows)).hexdigest()
        if not isinstance(held_out_expected_sha256, str) or not _SHA256.fullmatch(held_out_expected_sha256):
            raise ValueError("held_out_manifest_digest_invalid")
        if dataset_sha256 != held_out_expected_sha256:
            raise ValueError("held_out_manifest_digest_mismatch")
        baseline_predictions_sha256 = hashlib.sha256(_canonical(list(baseline_predictions))).hexdigest()
        challenger_predictions_sha256 = hashlib.sha256(_canonical(list(challenger_predictions))).hexdigest()
        baseline_score, baseline_correct = _score(dataset_rows, baseline_predictions)
        challenger_score, challenger_correct = _score(dataset_rows, challenger_predictions)

        record = {
            "experiment_id": experiment_id,
            "baseline": {
                "candidate_id": baseline_candidate_id,
                "artifact_sha256": baseline_artifact_sha256,
                "score": baseline_score,
                "correct_count": baseline_correct,
                "predictions_sha256": baseline_predictions_sha256,
            },
            "challenger": {
                "candidate_id": challenger_candidate_id,
                "artifact_sha256": challenger_artifact_sha256,
                "score": challenger_score,
                "correct_count": challenger_correct,
                "predictions_sha256": challenger_predictions_sha256,
            },
            "evaluator": {
                "evaluator_id": evaluator_id,
                "version": evaluator_version,
                "metric": "exact_match_rate",
                "direction": "higher",
                "minimum_delta": float(minimum_delta),
            },
            "held_out": {
                "dataset_id": f"{experiment_id}:held-out",
                "dataset_sha256": dataset_sha256,
                "sample_count": len(dataset_rows),
                "locked": held_out_locked,
            },
            "safety": dict(safety),
        }
        result = evaluate_comparison(record)
        return {
            "record": record,
            "result": result,
            "baseline_correct": baseline_correct,
            "challenger_correct": challenger_correct,
            "evaluator_kind": "deterministic_exact_match",
        }
    except (TypeError, ValueError, OverflowError) as exc:
        return {
            "record": None,
            "result": {
                "experiment_id": experiment_id if isinstance(experiment_id, str) else "",
                "status": "BLOCKED",
                "reason": str(exc)[:120],
                "improvement": None,
                "evidence_sha256": None,
                "execution_authorized": False,
                "patch_authorized": False,
                "hold_clear_authorized": False,
                "stop_clear_authorized": False,
                "merge_deploy_authorized": False,
                "required_human_approval": True,
            },
            "baseline_correct": None,
            "challenger_correct": None,
            "evaluator_kind": "deterministic_exact_match",
        }
