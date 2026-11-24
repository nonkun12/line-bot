from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from scripts.produce_looplab_simulator_artifact import (
    build_payload,
    canonical,
    write_signed_artifact,
    ensure_output_is_separate,
)


def _fixture(tmp_path):
    dataset = [{"sample_id": "a", "input": "question A"}, {"sample_id": "b", "input": "question B"}]
    paths = {}
    for name, value in {
        "dataset": dataset,
        "baseline_predictions": [
            {"sample_id": "a", "output": "baseline A"},
            {"sample_id": "b", "output": "baseline B"},
        ],
        "challenger_predictions": [
            {"sample_id": "a", "output": "challenger A"},
            {"sample_id": "b", "output": "challenger B"},
        ],
    }.items():
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    for name, value in {"baseline_artifact": b"baseline-model", "challenger_artifact": b"challenger-model"}.items():
        paths[name] = tmp_path / name
        paths[name].write_bytes(value)
    return paths


def _build(paths):
    return build_payload(
        dataset_path=paths["dataset"],
        baseline_predictions_path=paths["baseline_predictions"],
        challenger_predictions_path=paths["challenger_predictions"],
        baseline_artifact_path=paths["baseline_artifact"],
        challenger_artifact_path=paths["challenger_artifact"],
        experiment_id="exp-001",
        run_id="1234",
        commit_sha="a" * 40,
        created_at=1000,
    )


def test_producer_binds_signed_artifact_to_run_dataset_and_candidates(tmp_path):
    paths = _fixture(tmp_path)
    payload = _build(paths)
    assert payload["dataset_sha256"] == hashlib.sha256(canonical(json.loads(paths["dataset"].read_text()))).hexdigest()
    assert payload["source_run_id"] == "1234"
    assert payload["source_commit_sha"] == "a" * 40
    assert payload["baseline"]["artifact_sha256"] == hashlib.sha256(b"baseline-model").hexdigest()
    assert payload["challenger"]["artifact_sha256"] == hashlib.sha256(b"challenger-model").hexdigest()
    output = tmp_path / "out" / "simulator.json"
    key = b"s" * 40
    write_signed_artifact(payload, output, key)
    envelope = json.loads(output.read_text(encoding="utf-8"))
    expected = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(envelope["signature"], expected)


def test_producer_rejects_missing_or_malformed_run_binding(tmp_path):
    paths = _fixture(tmp_path)
    with pytest.raises(ValueError, match="github_run_id_missing_or_invalid"):
        build_payload(
            dataset_path=paths["dataset"],
            baseline_predictions_path=paths["baseline_predictions"],
            challenger_predictions_path=paths["challenger_predictions"],
            baseline_artifact_path=paths["baseline_artifact"],
            challenger_artifact_path=paths["challenger_artifact"],
            experiment_id="exp-001",
            run_id="",
            commit_sha="a" * 40,
        )


def test_producer_rejects_incomplete_or_substituted_predictions(tmp_path):
    paths = _fixture(tmp_path)
    paths["challenger_predictions"].write_text(
        json.dumps([{"sample_id": "a", "output": "only one"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="prediction_coverage_incomplete"):
        _build(paths)


def test_producer_rejects_duplicate_prediction_ids(tmp_path):
    paths = _fixture(tmp_path)
    paths["baseline_predictions"].write_text(
        json.dumps([
            {"sample_id": "a", "output": "first"},
            {"sample_id": "a", "output": "duplicate"},
        ]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="prediction_sample_duplicate"):
        _build(paths)


def test_producer_rejects_missing_candidate_artifact(tmp_path):
    paths = _fixture(tmp_path)
    paths["challenger_artifact"].unlink()
    with pytest.raises(ValueError, match="candidate_artifact_missing"):
        _build(paths)



def test_producer_refuses_output_path_that_aliases_an_input(tmp_path):
    paths = _fixture(tmp_path)
    with pytest.raises(ValueError, match="output_path_must_not_overwrite_input"):
        ensure_output_is_separate(paths["dataset"], list(paths.values()))
