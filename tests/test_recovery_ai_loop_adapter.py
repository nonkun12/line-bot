"""Regression tests for the distributed-loop Recovery AI adapter."""
import pytest

from scripts.recovery_ai import RecoveryStateError, RecoveryStore
from scripts.recovery_ai_loop_adapter import _category, record_loop_outcome


@pytest.mark.parametrize(("reason", "expected"), [
    ("rate_limited_http_429", "rate_limited"),
    ("service_unavailable_http_503", "service_unavailable"),
    ("network_transient_connection_reset", "network_transient"),
    ("task_timeout", "timeout"),
    ("sha_mismatch", "security_violation"),
    ("vault_write_failed: PermissionError", "state_persistence_failure"),
])
def test_failure_reason_maps_to_expected_recovery_category(reason, expected):
    assert _category({"status": "FAIL", "failure_reason": reason}) == expected


def test_verified_pass_is_recorded_and_resets_streak(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "PASS", "exit_code": 0, "failure_reason": ""
    })
    assert result == {"recorded": True, "status": "PASS", "verified": True}
    assert store.task_status("task-a")["consecutive_failures"] == 0


def test_timeout_is_bounded_repair_decision_and_does_not_execute_repair(tmp_path, monkeypatch):
    monkeypatch.delenv("RECOVERY_AI_APPLE_ADVISOR", raising=False)
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "TIMEOUT", "exit_code": 1, "failure_reason": "task_timeout"
    })
    assert result["decision"]["action"] == "REPAIR_ONCE"
    assert result["decision"]["reason"] == "bounded_repair_attempt"
    assert result["apple_advisor"] == {"available": False, "reason": "advisor_not_enabled"}


def test_invalid_evidence_holds_for_human_review(tmp_path, monkeypatch):
    monkeypatch.delenv("RECOVERY_AI_APPLE_ADVISOR", raising=False)
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "failure_reason": "summary_test_evidence_missing_or_invalid"
    })
    assert result["decision"]["action"] == "HOLD"
    assert result["decision"]["requires_human"] is True


def test_vault_write_failure_stops_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "failure_reason": "vault_write_failed: PermissionError"
    })
    assert result["decision"]["action"] == "STOP_FAIL_CLOSED"
    assert result["decision"]["requires_human"] is True
    assert result["apple_advisor"] == {"available": False, "reason": "state_persistence_failure"}


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


def test_verified_no_change_is_success_not_a_failure(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "NO_CHANGE", "exit_code": 0, "failure_reason": "no_change"
    })
    assert result == {"recorded": True, "status": "NO_CHANGE", "verified": True}
    assert store.task_status("task-a")["consecutive_failures"] == 0


def test_opt_in_calls_advisor_after_persist_and_keeps_decision(monkeypatch, tmp_path):
    import scripts.apple_foundation_models_advisor as advisor

    calls = []
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    monkeypatch.setattr(advisor, "advise", lambda task_id, category: (
        calls.append((task_id, category)) or advisor.AdvisorResult(True, "Inspect timeout boundary", "advisory_only")
    ))
    path = tmp_path / "recovery.json"
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "TIMEOUT", "exit_code": 1, "failure_reason": "task_timeout"
    })
    assert calls == [("task-a", "timeout")]
    assert result["decision"]["action"] == "REPAIR_ONCE"
    assert result["apple_advisor"] == {
        "available": True, "advice": "Inspect timeout boundary", "reason": "advisory_only"
    }
    assert RecoveryStore(path).task_status("task-a")["consecutive_failures"] == 1


def test_advisor_failure_does_not_change_deterministic_decision(monkeypatch, tmp_path):
    import scripts.apple_foundation_models_advisor as advisor

    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    monkeypatch.setattr(advisor, "advise", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "TIMEOUT", "exit_code": 1, "failure_reason": "task_timeout"
    })
    assert result["decision"]["action"] == "REPAIR_ONCE"
    assert result["apple_advisor"] == {"available": False, "reason": "advisor_unexpected_error"}


def test_success_never_calls_optional_advisor(monkeypatch, tmp_path):
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "PASS", "exit_code": 0, "failure_reason": ""
    })
    assert result == {"recorded": True, "status": "PASS", "verified": True}

def test_recovery_state_write_failure_stops_before_advisor(monkeypatch, tmp_path):
    import scripts.apple_foundation_models_advisor as advisor

    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    calls = []
    monkeypatch.setattr(advisor, "advise", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        RecoveryStore, "_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RecoveryStateError("write blocked")),
    )
    with pytest.raises(RecoveryStateError):
        record_loop_outcome(tmp_path / "recovery.json", {
            "task_id": "task-write-fail", "status": "FAIL", "exit_code": 1,
            "failure_reason": "task_timeout",
        })
    assert calls == []


def test_recovery_state_readback_mismatch_fails_closed(monkeypatch, tmp_path):
    original = RecoveryStore.task_status

    def mismatched_status(self, task_id):
        status = original(self, task_id)
        status["last_category"] = "unknown"
        return status

    monkeypatch.setattr(RecoveryStore, "task_status", mismatched_status)
    with pytest.raises(RecoveryStateError, match="read-back verification failed"):
        record_loop_outcome(tmp_path / "recovery.json", {
            "task_id": "task-readback-mismatch", "status": "FAIL", "exit_code": 1,
            "failure_reason": "task_timeout",
        })

def test_transient_retry_fast_path_skips_advisor_even_when_opted_in(monkeypatch, tmp_path):
    import scripts.apple_foundation_models_advisor as advisor

    calls = []
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    monkeypatch.setattr(advisor, "advise", lambda *args, **kwargs: calls.append(args))
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-fast-retry", "status": "FAIL", "exit_code": 1,
        "failure_reason": "network_transient",
    })
    assert result["decision"]["action"] == "RETRY"
    assert result["apple_advisor"] == {
        "available": False, "reason": "fast_path_no_advice_needed"
    }
    assert calls == []

