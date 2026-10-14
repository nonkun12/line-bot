"""Isolated fault-injection test for recovery-duration instrumentation.

This is a synthetic local test only: it does not alter production services,
apply patches, merge, or deploy. It measures failure-recording to verified
recovery and validates the emitted duration fields.
"""
from datetime import datetime, timezone
from time import monotonic

from scripts.recovery_ai import RecoveryStore, elapsed_seconds


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def test_synthetic_timeout_records_measurable_recovery_duration(tmp_path):
    store = RecoveryStore(tmp_path / "isolated-recovery-state.json")

    started_clock = monotonic()
    failure_at = _iso_now()
    decision = store.record_failure("isolated-fault-test", "timeout")
    repair_started_at = _iso_now()

    # Simulated recovery: no shell commands, network, or production mutation.
    store.record_success("isolated-fault-test", verified=True)
    recovered_at = _iso_now()
    elapsed_clock_seconds = round(monotonic() - started_clock, 6)

    metrics = {
        "failure_at": failure_at,
        "repair_started_at": repair_started_at,
        "recovered_at": recovered_at,
        "failure_to_recovery_seconds": elapsed_seconds(failure_at, recovered_at),
        "repair_execution_seconds": elapsed_seconds(repair_started_at, recovered_at),
        "measured_monotonic_seconds": elapsed_clock_seconds,
        "decision": decision.action,
        "verified_success": store.task_status("isolated-fault-test")["consecutive_failures"] == 0,
    }

    assert metrics["decision"] == "REPAIR_ONCE"
    assert metrics["verified_success"] is True
    assert metrics["failure_to_recovery_seconds"] >= 0
    assert metrics["repair_execution_seconds"] >= 0
    assert metrics["measured_monotonic_seconds"] >= 0
    assert metrics["failure_at"] <= metrics["repair_started_at"] <= metrics["recovered_at"]



def test_adapter_failure_to_verified_success_duration(tmp_path):
    """Exercise the real adapter boundary with isolated state and a bounded retry."""
    from time import sleep

    from scripts.recovery_ai_loop_adapter import record_loop_outcome

    path = tmp_path / "adapter-recovery-state.json"
    started = monotonic()
    failure_at = _iso_now()
    failed_payload = {
        "task_id": "adapter-fault-test",
        "status": "TIMEOUT",
        "exit_code": 1,
        "failure_reason": "task_timeout",
    }
    failed = record_loop_outcome(path, failed_payload)
    assert failed["recorded"] is True
    assert failed["decision"]["action"] == "REPAIR_ONCE"

    # Simulate the caller's single bounded retry; no worker, shell, or production
    # service is invoked. The success is accepted only with fresh run identity.
    sleep(0.02)
    success_at = _iso_now()
    succeeded = record_loop_outcome(path, {
        "task_id": "adapter-fault-test",
        "status": "PASS",
        "exit_code": 0,
        "failure_reason": "",
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "run_nonce": "c" * 32,
    })
    elapsed = round(monotonic() - started, 6)

    assert succeeded == {"recorded": True, "status": "PASS", "verified": True}
    assert RecoveryStore(path).task_status("adapter-fault-test")["consecutive_failures"] == 0
    assert elapsed >= 0.02
    assert elapsed_seconds(failure_at, success_at) >= 0
