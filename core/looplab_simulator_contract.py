"""Validate provenance and prediction coverage for trusted LoopLab simulator artifacts.

This validator does not execute models or candidates. It binds a signed producer
payload to the current Distributed Loop run, source commit, and locked dataset.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_PRODUCER_ID = "distributed-loop-simulator-producer.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def validate_simulator_provenance(
    simulator: Mapping[str, Any],
    dataset: Sequence[Mapping[str, Any]],
    *,
    dataset_sha256: str,
    expected_run_id: str,
    expected_commit_sha: str,
    now: int,
    max_age_seconds: int = 300,
) -> None:
    """Raise ValueError unless signed simulator metadata is bound to this run."""
    if not isinstance(simulator, Mapping):
        raise ValueError("simulator_payload_invalid")
    if simulator.get("schema_version") != 1:
        raise ValueError("simulator_schema_version_unsupported")
    if simulator.get("producer_id") != _PRODUCER_ID:
        raise ValueError("simulator_producer_identity_invalid")
    experiment_id = simulator.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("simulator_experiment_id_invalid")
    if simulator.get("dataset_id") != experiment_id + ":held-out":
        raise ValueError("simulator_dataset_identity_mismatch")
    if simulator.get("dataset_sha256") != dataset_sha256 or not _SHA64.fullmatch(dataset_sha256):
        raise ValueError("simulator_dataset_digest_mismatch")

    run_id = simulator.get("source_run_id")
    if not isinstance(run_id, str) or not run_id.isdigit() or run_id != str(expected_run_id):
        raise ValueError("simulator_source_run_mismatch")
    commit_sha = simulator.get("source_commit_sha")
    if (
        not isinstance(commit_sha, str)
        or not (_SHA40.fullmatch(commit_sha) or _SHA64.fullmatch(commit_sha))
        or commit_sha != expected_commit_sha
    ):
        raise ValueError("simulator_source_commit_mismatch")

    created_at = simulator.get("created_at")
    if type(created_at) is not int:
        raise ValueError("simulator_timestamp_invalid")
    age = now - created_at
    if age < -30 or age > max_age_seconds:
        raise ValueError("simulator_artifact_stale_or_future")

    expected_ids = []
    for row in dataset:
        if not isinstance(row, Mapping):
            raise ValueError("held_out_dataset_row_invalid")
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("held_out_dataset_sample_id_invalid")
        expected_ids.append(sample_id)
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("held_out_dataset_sample_ids_duplicate")

    for candidate_name in ("baseline", "challenger"):
        candidate = simulator.get(candidate_name)
        if not isinstance(candidate, Mapping):
            raise ValueError("simulator_candidate_missing")
        predictions = candidate.get("predictions")
        if not isinstance(predictions, list) or len(predictions) != len(expected_ids):
            raise ValueError("simulator_prediction_coverage_incomplete")
        actual_ids = []
        for prediction in predictions:
            if not isinstance(prediction, Mapping):
                raise ValueError("simulator_prediction_invalid")
            sample_id = prediction.get("sample_id")
            if not isinstance(sample_id, str) or not isinstance(prediction.get("output"), str):
                raise ValueError("simulator_prediction_schema_invalid")
            actual_ids.append(sample_id)
        if len(actual_ids) != len(set(actual_ids)):
            raise ValueError("simulator_prediction_sample_ids_duplicate")
        if set(actual_ids) != set(expected_ids):
            raise ValueError("simulator_prediction_sample_coverage_mismatch")


__all__ = ["validate_simulator_provenance"]
