from __future__ import annotations

import hashlib
import hmac
import json

from scripts.looplab_postrun_gate import evaluate_postrun


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _signed(payload, key):
    return {"payload": payload, "signature": hmac.new(key.encode(), _canonical(payload), hashlib.sha256).hexdigest()}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _inputs(tmp_path):
    keys = {
        "LOOPLAB_SIMULATOR_HMAC_KEY": "s" * 40,
        "LOOPLAB_DATASET_REGISTRY_HMAC_KEY": "r" * 40,
        "LOOPLAB_SAFETY_HMAC_KEY": "t" * 40,
        "LOOPLAB_ADAPTER_HMAC_KEY": "a" * 40,
        "LOOPLAB_RSI_EVIDENCE_HMAC_KEY": "e" * 40,
    }
    dataset = [
        {"sample_id": "one", "input": "1+1", "expected": "2"},
        {"sample_id": "two", "input": "2+2", "expected": "4"},
    ]
    digest = hashlib.sha256(_canonical(dataset)).hexdigest()
    simulator = {
        "schema_version": 1,
        "producer_id": "distributed-loop-simulator-producer.v1",
        "experiment_id": "looplab-ci-001",
        "dataset_id": "looplab-ci-001:held-out",
        "dataset_sha256": digest,
        "source_run_id": "12345",
        "source_commit_sha": "a" * 40,
        "created_at": 1000,
        "baseline": {
            "candidate_id": "baseline",
            "artifact_sha256": "1" * 64,
            "predictions": [
                {"sample_id": "one", "output": "0"},
                {"sample_id": "two", "output": "0"},
            ],
        },
        "challenger": {
            "candidate_id": "challenger",
            "artifact_sha256": "2" * 64,
            "predictions": [
                {"sample_id": "one", "output": "2"},
                {"sample_id": "two", "output": "4"},
            ],
        },
    }
    registry = {
        "datasets": {
            "looplab-ci-001:held-out": {
                "dataset_sha256": digest,
                "sample_count": 2,
                "minimum_sample_count": 2,
                "locked": True,
            }
        }
    }
    safety = {
        "stop_state": "INACTIVE",
        "global_hold_state": "CLEAR",
        "issued_at": 900,
        "expires_at": 1100,
        "execution_enabled": False,
        "free_only": True,
        "budget_known": True,
        "budget_remaining_units": 1,
        "paid_fallback_enabled": False,
    }
    paths = {
        "simulator": tmp_path / "simulator.json",
        "dataset": tmp_path / "dataset.json",
        "registry": tmp_path / "registry.json",
        "safety": tmp_path / "safety.json",
        "output": tmp_path / "result.json",
    }
    _write(paths["simulator"], _signed(simulator, keys["LOOPLAB_SIMULATOR_HMAC_KEY"]))
    _write(paths["dataset"], dataset)
    _write(paths["registry"], _signed(registry, keys["LOOPLAB_DATASET_REGISTRY_HMAC_KEY"]))
    _write(paths["safety"], _signed(safety, keys["LOOPLAB_SAFETY_HMAC_KEY"]))
    keys["GITHUB_RUN_ID"] = "12345"
    keys["GITHUB_SHA"] = "a" * 40
    return keys, paths


def test_signed_postrun_inputs_evaluate_but_do_not_ingest_into_rsi(tmp_path):
    keys, paths = _inputs(tmp_path)
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "PASS"
    assert result["evaluation"]["adapter_signature"]
    assert result["rsi_ingestion"] == "RECORDED"
    assert result["rsi"]["recorded"] is True
    assert result["rsi_ledger"]
    assert result["authority"]["execution_authorized"] is False
    assert json.loads(paths["output"].read_text())["status"] == "PASS"


def test_missing_artifacts_and_keys_fail_closed(tmp_path):
    result = evaluate_postrun(
        simulator_path=tmp_path / "missing-simulator.json",
        dataset_path=tmp_path / "missing-dataset.json",
        registry_path=tmp_path / "missing-registry.json",
        safety_path=tmp_path / "missing-safety.json",
        output_path=tmp_path / "result.json",
        env={},
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["evaluation"] is None
    assert result["authority"]["merge_deploy_authorized"] is False


def test_invalid_registry_signature_blocks_evaluation(tmp_path):
    keys, paths = _inputs(tmp_path)
    _write(paths["registry"], {"payload": {"datasets": {}}, "signature": "0" * 64})
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "dataset_registry_signature_invalid"


def test_active_hold_or_stop_blocks_evaluation(tmp_path):
    keys, paths = _inputs(tmp_path)
    active = {
        "stop_state": "INACTIVE",
        "global_hold_state": "ACTIVE",
        "issued_at": 900,
        "expires_at": 1100,
        "execution_enabled": False,
        "free_only": True,
        "budget_known": True,
        "budget_remaining_units": 1,
        "paid_fallback_enabled": False,
    }
    _write(paths["safety"], _signed(active, keys["LOOPLAB_SAFETY_HMAC_KEY"]))
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "global_hold_active_or_unverified"



def test_simulator_artifact_must_match_current_distributed_run(tmp_path):
    keys, paths = _inputs(tmp_path)
    payload = json.loads(paths["simulator"].read_text(encoding="utf-8"))["payload"]
    payload["source_run_id"] = "99999"
    _write(paths["simulator"], _signed(payload, keys["LOOPLAB_SIMULATOR_HMAC_KEY"]))
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "simulator_source_run_mismatch"


def test_simulator_predictions_must_cover_locked_dataset_exactly(tmp_path):
    keys, paths = _inputs(tmp_path)
    payload = json.loads(paths["simulator"].read_text(encoding="utf-8"))["payload"]
    payload["challenger"]["predictions"].pop()
    _write(paths["simulator"], _signed(payload, keys["LOOPLAB_SIMULATOR_HMAC_KEY"]))
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "simulator_prediction_coverage_incomplete"


def test_stale_simulator_artifact_blocks_before_evaluation(tmp_path):
    keys, paths = _inputs(tmp_path)
    payload = json.loads(paths["simulator"].read_text(encoding="utf-8"))["payload"]
    payload["created_at"] = 600
    _write(paths["simulator"], _signed(payload, keys["LOOPLAB_SIMULATOR_HMAC_KEY"]))
    result = evaluate_postrun(
        simulator_path=paths["simulator"],
        dataset_path=paths["dataset"],
        registry_path=paths["registry"],
        safety_path=paths["safety"],
        output_path=paths["output"],
        env=keys,
        now=1000,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "simulator_artifact_stale_or_future"
