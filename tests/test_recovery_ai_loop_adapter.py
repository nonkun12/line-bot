"""Regression tests for the distributed-loop Recovery AI adapter."""
import json

import pytest

from scripts.recovery_ai import RecoveryStateError, RecoveryStore
from scripts.recovery_ai_loop_adapter import record_loop_outcome


def test_verified_pass_is_recorded_and_resets_streak(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "PASS", "exit_code": 0, "failure_reason": "",
        "base_sha": "a" * 40, "produced_sha": "b" * 40, "run_nonce": "c" * 32
    })
    assert result == {"recorded": True, "status": "PASS", "verified": True}
    assert store.task_status("task-a")["consecutive_failures"] == 0


def test_timeout_is_bounded_repair_decision_and_does_not_execute_repair(tmp_path):
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "TIMEOUT", "exit_code": 1, "failure_reason": "task_timeout"
    })
    assert result["decision"]["action"] == "REPAIR_ONCE"
    assert result["decision"]["reason"] == "bounded_repair_attempt"


def test_invalid_evidence_holds_for_human_review(tmp_path):
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "failure_reason": "summary_test_evidence_missing_or_invalid"
    })
    assert result["decision"]["action"] == "HOLD"
    assert result["decision"]["requires_human"] is True


def test_corrupt_recovery_state_fails_closed(tmp_path):
    path = tmp_path / "recovery.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RecoveryStateError):
        record_loop_outcome(path, {
            "task_id": "task-a", "status": "FAIL", "exit_code": 1, "failure_reason": "unknown"
        })


def test_queue_summary_without_task_id_is_not_recorded(tmp_path):
    assert record_loop_outcome(tmp_path / "recovery.json", {
        "status": "NOT_RUN", "exit_code": 78, "failure_reason": "queue_empty"
    }) == {"recorded": False, "reason": "no_task_id"}


def test_success_without_current_run_identity_is_held(tmp_path):
    path = tmp_path / "recovery.json"
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "PASS", "exit_code": 0, "failure_reason": ""
    })
    assert result["recorded"] is True
    assert result["decision"]["action"] == "HOLD"
    assert result["decision"]["requires_human"] is True
    assert RecoveryStore(path).task_status("task-a")["consecutive_failures"] == 1


def test_verified_no_change_is_success_not_a_failure(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "NO_CHANGE", "exit_code": 0, "failure_reason": "no_change",
        "base_sha": "a" * 40, "produced_sha": "a" * 40, "run_nonce": "b" * 32
    })
    assert result == {"recorded": True, "status": "NO_CHANGE", "verified": True}
    assert store.task_status("task-a")["consecutive_failures"] == 0


def test_state_write_failure_fails_closed_and_preserves_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-existing", "timeout")
    before = json.loads(path.read_text(encoding="utf-8"))

    def fail_replace(_source, _destination):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("scripts.recovery_ai.os.replace", fail_replace)
    with pytest.raises(RecoveryStateError, match="persistence failed"):
        record_loop_outcome(path, {
            "task_id": "task-new",
            "status": "FAIL",
            "exit_code": 1,
            "failure_reason": "timeout",
        })

    assert json.loads(path.read_text(encoding="utf-8")) == before
    assert store.task_status("task-existing")["consecutive_failures"] == 1
    assert store.task_status("task-new") == {}


def test_success_without_run_identity_invalidates_task_result(tmp_path):
    result_payload = {
        "task_id": "task-a",
        "status": "PASS",
        "exit_code": 0,
        "failure_reason": "",
    }
    outcome = record_loop_outcome(tmp_path / "recovery.json", result_payload)
    assert outcome["decision"]["action"] == "HOLD"
    assert result_payload["status"] == "FAIL"
    assert result_payload["exit_code"] == 1
    assert result_payload["failure_reason"] == "recovery_ai_invalid_evidence"
