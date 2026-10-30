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
    # RAG advisory metadata may be added without changing the stable outcome contract.
    assert result["recorded"] is True
    assert result["status"] == "PASS"
    assert result["verified"] is True
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


@pytest.mark.parametrize("failure_reason", [
    "apply failed: change_too_large",
    "invalid_change_count_repair_failed",
    "invalid_old_new",
    "diff_marker_in_replacement",
    "apply failed: anchor_count_tests/test_rea_readonly_scanner.py:0",
])
def test_rejected_bounded_plan_is_invalid_task_and_requires_human_review(tmp_path, failure_reason):
    path = tmp_path / "recovery.json"
    result = record_loop_outcome(path, {
        "task_id": "task-invalid-plan", "status": "FAIL", "exit_code": 1,
        "failure_reason": failure_reason,
    })
    assert result["decision"]["action"] == "HOLD"
    assert result["decision"]["requires_human"] is True
    assert RecoveryStore(path).task_status("task-invalid-plan")["last_category"] == "invalid_task"


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
    # RAG advisory metadata may be added without changing the stable outcome contract.
    assert result["recorded"] is True
    assert result["status"] == "NO_CHANGE"
    assert result["verified"] is True
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


def test_all_pending_tasks_held_is_blocked_not_completed():
    from scripts.run_minimal_autonomous_loop import classify_final_outcome

    assert classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        all_tasks_held=True,
    ) == ("BLOCKED", "all_pending_tasks_held")


def test_held_task_classifier_fails_closed_on_post_run_gate_error():
    from scripts.run_minimal_autonomous_loop import classify_final_outcome

    assert classify_final_outcome(
        ["BLOCKED"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="failure",
        sheets_outcome="success",
        all_tasks_held=True,
    ) == ("BLOCKED", "held_queue_post_run_gate_failed:state")


def test_failed_recovery_state_persistence_blocks_final_completion():
    from scripts.run_minimal_autonomous_loop import classify_final_outcome

    assert classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="failure",
    ) == ("FAILED", "post_run_gate_failed:recovery_ai_persistence")



def test_rag_connection_records_sanitized_outcomes_and_reads_prior_history(tmp_path, monkeypatch):
    db_path = tmp_path / "recovery-rag.sqlite3"
    monkeypatch.setenv("RECOVERY_RAG_DB_PATH", str(db_path))
    monkeypatch.setenv("RECOVERY_RAG_NAMESPACE", "test-loop")

    first = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-rag-a", "status": "TIMEOUT", "exit_code": 1,
        "failure_reason": "task_timeout; never store this raw message",
    })
    second = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-rag-b", "status": "TIMEOUT", "exit_code": 1,
        "failure_reason": "task_timeout",
    })

    assert first["decision"]["action"] == "REPAIR_ONCE"
    assert first["recovery_rag"]["recorded"] is True
    assert second["recovery_rag"]["recorded"] is True
    assert second["recovery_rag"]["prior_matches"] == 1
    from rag_store import RagStore
    stored = RagStore(db_path).search(namespace="test-loop", query="timeout", limit=5)
    assert len(stored) == 2
    assert all("never store this raw message" not in item["content"] for item in stored)


def test_rag_storage_failure_does_not_change_recovery_ai_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOVERY_RAG_DB_PATH", str(tmp_path / "recovery-rag.sqlite3"))

    def fail_record(*args, **kwargs):
        raise OSError("raw private path should not be returned")

    monkeypatch.setattr("scripts.recovery_rag.record_outcome", fail_record)
    outcome = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-rag-failure", "status": "TIMEOUT", "exit_code": 1,
        "failure_reason": "task_timeout",
    })

    assert outcome["decision"]["action"] == "REPAIR_ONCE"
    assert outcome["recovery_rag"] == {"recorded": False, "error": "OSError"}


@pytest.mark.parametrize("failure_reason", [
    "control_tower_gate:task_definition_mismatch",
    "control_tower_head_changed",
])
def test_preflight_blocked_does_not_increment_recovery_failure_streak(tmp_path, failure_reason):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    before = store.task_status("task-a")

    outcome = record_loop_outcome(path, {
        "task_id": "task-a",
        "status": "BLOCKED",
        "exit_code": 1,
        "failure_reason": failure_reason,
    })

    assert outcome == {
        "recorded": False,
        "reason": "preflight_blocked_not_task_failure",
    }
    assert store.task_status("task-a") == before


def test_real_task_failure_still_increments_recovery_failure_streak(tmp_path):
    path = tmp_path / "recovery.json"
    outcome = record_loop_outcome(path, {
        "task_id": "task-a",
        "status": "FAIL",
        "exit_code": 1,
        "failure_reason": "task_runtime_failed",
    })
    assert outcome["recorded"] is True
    assert outcome["decision"]["consecutive_failures"] == 1

@pytest.mark.parametrize("boolean_exit_code", [False, True])
def test_boolean_exit_code_never_resets_recovery_failure_streak(tmp_path, boolean_exit_code):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-bool", "timeout")
    before = store.task_status("task-bool")["consecutive_failures"]

    result_payload = {
        "task_id": "task-bool",
        "status": "PASS",
        "exit_code": boolean_exit_code,
        "failure_reason": "",
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "run_nonce": "c" * 32,
    }
    outcome = record_loop_outcome(path, result_payload)

    assert outcome["recorded"] is True
    assert outcome["status"] == "FAIL"
    assert result_payload["status"] == "FAIL"
    assert result_payload["exit_code"] == 1
    assert result_payload["failure_reason"] == "recovery_ai_invalid_evidence"
    assert store.task_status("task-bool")["consecutive_failures"] == before + 1

def test_noncanonical_uppercase_sha_does_not_reset_recovery_failure_streak(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-sha", "timeout")
    before = store.task_status("task-sha")["consecutive_failures"]

    result_payload = {
        "task_id": "task-sha",
        "status": "PASS",
        "exit_code": 0,
        "failure_reason": "",
        "base_sha": "A" * 40,
        "produced_sha": "B" * 40,
        "run_nonce": "c" * 32,
    }
    outcome = record_loop_outcome(path, result_payload)

    assert outcome["recorded"] is True
    assert outcome["status"] == "FAIL"
    assert result_payload["status"] == "FAIL"
    assert result_payload["failure_reason"] == "recovery_ai_invalid_evidence"
    assert store.task_status("task-sha")["consecutive_failures"] == before + 1


def test_verified_success_persists_exact_run_identity(tmp_path):
    path = tmp_path / "recovery.json"
    payload = {
        "task_id": "task-bound", "status": "PASS", "exit_code": 0,
        "failure_reason": "", "base_sha": "a" * 40,
        "produced_sha": "b" * 40, "run_nonce": "c" * 32,
    }
    outcome = record_loop_outcome(path, payload)
    expected = {
        "task_id": "task-bound", "base_sha": "a" * 40,
        "produced_sha": "b" * 40, "run_nonce": "c" * 32,
    }
    assert outcome["evidence"] == expected
    assert RecoveryStore(path).task_status("task-bound")["last_success_evidence"] == expected


def test_recovery_store_rejects_success_evidence_for_another_task(tmp_path):
    store = RecoveryStore(tmp_path / "recovery.json")
    with pytest.raises(ValueError, match="task identity mismatch"):
        store.record_success("task-a", verified=True, evidence={
            "task_id": "task-b", "base_sha": "a" * 40,
            "produced_sha": "b" * 40, "run_nonce": "c" * 32,
        })
