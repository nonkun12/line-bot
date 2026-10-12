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
