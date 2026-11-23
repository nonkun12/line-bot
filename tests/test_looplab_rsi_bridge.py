from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from core.looplab_rsi_bridge import record_evaluation_as_rsi_observation
from core.rsi_executor import EvidenceLedger, RSIControl, RSIExecutor, RSIError, canonical_digest


def _executor(tmp_path, *, hold=False):
    ledger = EvidenceLedger(tmp_path / "rsi-bridge.sqlite")
    executor = RSIExecutor(
        ledger,
        control_provider=lambda: RSIControl(hold, False, True, True, 10, False),
        verify_approval=lambda _: False,
        verify_evaluation=lambda _: False,
        verify_evidence_signature=lambda producer, digest, signature: (
            producer == "looplab-independent-evaluator" and signature == "sig:" + digest
        ),
        executor_id="rsi-bridge-test",
    )
    return executor, ledger


def _evaluation(status="FAIL"):
    dataset = [{"sample_id": "a", "expected": "yes"}]
    dataset_sha = hashlib.sha256(json.dumps(
        dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    challenger_score = 0.1 if status == "PASS" else 0.0
    record = {
        "experiment_id": "looplab-bridge-01",
        "baseline": {"candidate_id": "base", "artifact_sha256": "a" * 64, "score": 0.0},
        "challenger": {"candidate_id": "candidate", "artifact_sha256": "b" * 64, "score": challenger_score},
        "evaluator": {"evaluator_id": "rsi.exact_match.v1", "version": "1", "metric": "exact_match_rate", "direction": "higher", "minimum_delta": 0.0},
        "held_out": {"dataset_id": "fixture", "dataset_sha256": dataset_sha, "sample_count": 1, "locked": True},
        "safety": {"stop_state": "INACTIVE", "global_hold_state": "CLEAR"},
    }
    evidence_sha = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = {
        "experiment_id": "looplab-bridge-01",
        "status": status,
        "record": record,
        "evaluation": {"experiment_id": "looplab-bridge-01", "status": status, "reason": "minimum_improvement_not_met", "evidence_sha256": evidence_sha},
        "adapter_id": "looplab.simulator_rsi_bridge.v1",
    }
    result["adapter_signature"] = "trusted:" + canonical_digest({
        "adapter_id": result["adapter_id"],
        "experiment_id": result["experiment_id"],
        "record": result["record"],
        "evaluation": result["evaluation"],
    })
    return result


def _trust_kwargs():
    dataset = [{"sample_id": "a", "expected": "yes"}]
    dataset_sha = hashlib.sha256(json.dumps(
        dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return {
        "verify_adapter_signature": lambda adapter, digest, signature: (
            adapter == "looplab.simulator_rsi_bridge.v1" and signature == "trusted:" + digest
        ),
        "resolve_locked_dataset": lambda dataset_id: ({
            "dataset_sha256": dataset_sha, "sample_count": 1,
            "minimum_sample_count": 1, "locked": True,
        } if dataset_id == "fixture" else None),
    }


def test_fail_evaluation_becomes_signed_rsi_observation_and_diagnosis(tmp_path):
    executor, ledger = _executor(tmp_path)
    result = record_evaluation_as_rsi_observation(
        evaluation_result=_evaluation("FAIL"),
        executor=executor,
        producer_id="looplab-independent-evaluator",
        sign_digest=lambda digest: "sig:" + digest,
        created_at=123,
        **_trust_kwargs(),
    )
    assert result["recorded"] is True
    assert result["status"] == "FAIL"
    assert len(result["diagnosis_ids"]) == 1
    assert len(result["hypothesis_ids"]) == 1
    assert result["selected_plan"]["plan_digest"]
    assert result["execution_started"] is False
    assert ledger.verify()


def test_pass_evaluation_is_recorded_without_failure_diagnosis(tmp_path):
    executor, ledger = _executor(tmp_path)
    result = record_evaluation_as_rsi_observation(
        evaluation_result=_evaluation("PASS"),
        executor=executor,
        producer_id="looplab-independent-evaluator",
        sign_digest=lambda digest: "sig:" + digest,
        created_at=123,
        **_trust_kwargs(),
    )
    assert result["recorded"] is True
    assert result["diagnosis_ids"] == []
    assert result["hypothesis_ids"] == []
    assert result["selected_plan"] is None
    assert result["execution_started"] is False
    assert ledger.verify()


def test_blocked_evaluation_is_not_promoted_or_written(tmp_path):
    executor, ledger = _executor(tmp_path)
    result = record_evaluation_as_rsi_observation(
        evaluation_result={"experiment_id": "blocked-1", "status": "BLOCKED"},
        executor=executor,
        producer_id="looplab-independent-evaluator",
        sign_digest=lambda digest: "sig:" + digest,
        created_at=123,
    )
    assert result["recorded"] is False
    assert ledger.verify()


def test_global_hold_prevents_rsi_ingestion(tmp_path):
    executor, ledger = _executor(tmp_path, hold=True)
    with pytest.raises(RSIError, match="Global HOLD"):
        record_evaluation_as_rsi_observation(
            evaluation_result=_evaluation("FAIL"),
            executor=executor,
            producer_id="looplab-independent-evaluator",
            sign_digest=lambda digest: "sig:" + digest,
            created_at=123,
            **_trust_kwargs(),
        )
    assert ledger.verify()
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_evidence").fetchone()[0] == 0


def test_status_cannot_be_forged_even_when_both_status_fields_are_changed(tmp_path):
    executor, ledger = _executor(tmp_path)
    payload = _evaluation("FAIL")
    payload["status"] = "PASS"
    payload["evaluation"]["status"] = "PASS"
    with pytest.raises(ValueError, match="status_not_reproducible"):
        record_evaluation_as_rsi_observation(
            evaluation_result=payload,
            executor=executor,
            producer_id="looplab-independent-evaluator",
            sign_digest=lambda digest: "sig:" + digest,
            created_at=123,
        )
    assert ledger.verify()

def test_status_mismatch_is_rejected_before_ledger_write(tmp_path):
    executor, ledger = _executor(tmp_path)
    payload = _evaluation("FAIL")
    payload["evaluation"]["status"] = "PASS"
    with pytest.raises(ValueError, match="status_mismatch"):
        record_evaluation_as_rsi_observation(
            evaluation_result=payload,
            executor=executor,
            producer_id="looplab-independent-evaluator",
            sign_digest=lambda digest: "sig:" + digest,
            created_at=123,
        )
    assert ledger.verify()


def test_invalid_adapter_signature_is_rejected_before_ledger_write(tmp_path):
    executor, ledger = _executor(tmp_path)
    payload = _evaluation("FAIL")
    payload["adapter_signature"] = "forged"
    with pytest.raises(ValueError, match="adapter_signature_verification_failed"):
        record_evaluation_as_rsi_observation(
            evaluation_result=payload, executor=executor,
            producer_id="looplab-independent-evaluator",
            sign_digest=lambda digest: "sig:" + digest, created_at=123,
            **_trust_kwargs(),
        )
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_evidence").fetchone()[0] == 0


def test_unregistered_or_mismatched_dataset_is_rejected(tmp_path):
    executor, ledger = _executor(tmp_path)
    payload = _evaluation("FAIL")
    trust = _trust_kwargs()
    trust["resolve_locked_dataset"] = lambda _: {
        "dataset_sha256": "f" * 64, "sample_count": 1,
        "minimum_sample_count": 1, "locked": True,
    }
    with pytest.raises(ValueError, match="held_out_dataset_registry_mismatch"):
        record_evaluation_as_rsi_observation(
            evaluation_result=payload, executor=executor,
            producer_id="looplab-independent-evaluator",
            sign_digest=lambda digest: "sig:" + digest, created_at=123,
            **trust,
        )
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_evidence").fetchone()[0] == 0
