from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from core.looplab_experiment_adapter import ExperimentMemory, evaluate_simulator_run


def _fixture():
    dataset = [
        {"sample_id": "a", "expected": "alpha"},
        {"sample_id": "b", "expected": "beta"},
    ]
    digest = hashlib.sha256(json.dumps(
        dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    simulator_output = {
        "experiment_id": "looplab-smoke-001",
        "baseline": {
            "candidate_id": "base-v1", "artifact_sha256": "a" * 64,
            "predictions": [{"sample_id": "a", "output": "alpha"}, {"sample_id": "b", "output": "wrong"}],
        },
        "challenger": {
            "candidate_id": "candidate-v2", "artifact_sha256": "b" * 64,
            "predictions": [{"sample_id": "a", "output": "alpha"}, {"sample_id": "b", "output": "beta"}],
        },
    }
    return dataset, digest, simulator_output


def test_simulator_bridge_recomputes_scores_and_never_grants_authority():
    dataset, digest, output = _fixture()
    result = evaluate_simulator_run(
        simulator_output=output, held_out_dataset=dataset, held_out_locked=True,
        held_out_expected_sha256=digest,
        safety={"stop_state": "INACTIVE", "global_hold_state": "CLEAR"},
        minimum_delta=0.4,
    )
    assert result["status"] == "PASS"
    assert result["scores"] == {"baseline_correct": 1, "challenger_correct": 2}
    assert result["evaluation"]["evidence_sha256"]
    assert all(value is False for key, value in result["authority"].items() if key != "required_human_approval")
    assert result["authority"]["required_human_approval"] is True


def test_unlocked_fixture_is_blocked():
    dataset, digest, output = _fixture()
    result = evaluate_simulator_run(
        simulator_output=output, held_out_dataset=dataset, held_out_locked=False,
        held_out_expected_sha256=digest,
        safety={"stop_state": "INACTIVE", "global_hold_state": "CLEAR"},
    )
    assert result["status"] == "BLOCKED"
    assert result["evaluation"]["execution_authorized"] is False


def test_malformed_simulator_envelope_is_blocked():
    dataset, digest, output = _fixture()
    output["challenger"]["artifact_sha256"] = "not-a-digest"
    result = evaluate_simulator_run(
        simulator_output=output, held_out_dataset=dataset, held_out_locked=True,
        held_out_expected_sha256=digest,
        safety={"stop_state": "INACTIVE", "global_hold_state": "CLEAR"},
    )
    assert result["status"] == "BLOCKED"
    assert result["evaluation"]["patch_authorized"] is False


def test_experiment_memory_is_append_only_and_verifiable(tmp_path):
    memory = ExperimentMemory(tmp_path / "looplab.sqlite")
    item = {"experiment_id": "exp-1", "status": "PASS", "evidence": "f" * 64}
    digest = memory.append(item)
    assert len(digest) == 64
    assert memory.verify() is True
    assert memory.read_all() == (item,)
    with pytest.raises(ValueError, match="duplicate_experiment_evidence"):
        memory.append(item)
    with sqlite3.connect(tmp_path / "looplab.sqlite") as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE looplab_experiments SET payload='{}' WHERE seq=1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM looplab_experiments WHERE seq=1")


def test_experiment_memory_rejects_unknown_status(tmp_path):
    memory = ExperimentMemory(tmp_path / "looplab.sqlite")
    with pytest.raises(ValueError, match="experiment_status_invalid"):
        memory.append({"experiment_id": "exp-2", "status": "EXECUTE"})
