"""Safety and recovery regression tests for scripts.recovery_ai."""
import json

import pytest

from scripts.recovery_ai import (
    RecoveryStateError,
    RecoveryStore,
    elapsed_seconds,
    failure_fingerprint,
)


def test_transient_failure_uses_bounded_retry_and_backoff(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    first = store.record_failure("task-a", "network_transient", transient_attempt=1)
    second = store.record_failure("task-a", "network_transient", transient_attempt=2)
    third = store.record_failure("task-a", "network_transient", transient_attempt=3)
    assert (first.action, first.retry_after_seconds) == ("RETRY", 30)
    assert (second.action, second.retry_after_seconds) == ("RETRY", 60)
    assert third.action == "HOLD"
    assert store.task_status("task-a")["held"] is True


def test_same_deterministic_failure_is_not_repaired_repeatedly(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    first = store.record_failure("task-a", "test_regression", ["tests/test_x.py::test_y"])
    second = store.record_failure("task-a", "test_regression", ["tests/test_x.py::test_y"])
    assert first.action == "REPAIR_ONCE"
    assert second.action == "HOLD"
    assert second.reason == "repair_budget_exhausted"


def test_three_failures_hold_task_even_if_fingerprints_change(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    store.record_failure("task-a", "test_regression", ["test.one"])
    store.record_failure("task-a", "timeout", ["test.two"])
    decision = store.record_failure("task-a", "process_crash", ["test.three"])
    assert decision.action == "HOLD"
    assert decision.consecutive_failures == 3


def test_non_repairable_failure_holds_immediately(tmp_path):
    decision = RecoveryStore(tmp_path / "state.json").record_failure("task-a", "security_violation")
    assert decision.action == "HOLD"
    assert decision.requires_human is True


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RecoveryStateError):
        RecoveryStore(path).record_failure("task-a", "timeout")


def test_failure_streak_resets_only_after_verified_success(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    store.record_failure("task-a", "timeout")
    with pytest.raises(ValueError):
        store.record_success("task-a", verified=False)
    store.record_success("task-a", verified=True, evidence={
        "task_id": "task-a", "base_sha": "a" * 40,
        "produced_sha": "b" * 40, "run_nonce": "c" * 32,
    })
    status = store.task_status("task-a")
    assert status["consecutive_failures"] == 0
    assert "last_success_at" in status


def test_checkpoint_must_be_verified_and_is_resumable(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    with pytest.raises(ValueError):
        store.save_checkpoint("task-a", "checkpoint-1", verified=False)
    store.save_checkpoint("task-a", "checkpoint-1", verified=True)
    checkpoint = store.resumable_checkpoint()
    assert checkpoint["task_id"] == "task-a"
    assert checkpoint["checkpoint_id"] == "checkpoint-1"
    assert checkpoint["verified"] is True


def test_held_task_requires_explicit_cause_fixed_confirmation(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    for _ in range(3):
        decision = store.record_failure("task-a", "timeout")
    assert decision.action == "HOLD"
    with pytest.raises(ValueError):
        store.resume_held_task("task-a", cause_fixed=False)
    store.resume_held_task("task-a", cause_fixed=True)
    assert store.task_status("task-a")["held"] is False
    assert store.task_status("task-a")["consecutive_failures"] == 0
    assert store.task_status("task-a")["resume_requires_review"] is True


def test_fingerprint_is_stable_and_does_not_include_raw_error_output():
    a = failure_fingerprint("task-a", "test_regression", ["tests/a.py::test_b", "tests/a.py::test_b"])
    b = failure_fingerprint("task-a", "test_regression", ["tests/a.py::test_b"])
    assert a == b
    assert "token" not in a


def test_elapsed_seconds_requires_aware_nonnegative_timestamps():
    assert elapsed_seconds("2026-10-11T00:00:00+00:00", "2026-10-11T00:00:02.345+00:00") == 2.345
    with pytest.raises(ValueError):
        elapsed_seconds("2026-10-11T00:00:00", "2026-10-11T00:00:01+00:00")
    with pytest.raises(ValueError):
        elapsed_seconds("2026-10-11T00:00:02+00:00", "2026-10-11T00:00:01+00:00")
