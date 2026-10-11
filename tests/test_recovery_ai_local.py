from dataclasses import replace

import pytest

from scripts import recovery_ai_local
from scripts.apple_foundation_models_advisor import AdvisorResult
from scripts.recovery_ai import RecoveryDecision, RecoveryStateError


class FakeStore:
    def __init__(self, decision=None, error=None):
        self.decision = decision or RecoveryDecision(
            action="REPAIR_ONCE",
            reason="bounded_repair_attempt",
            task_id="task-1",
            fingerprint="a" * 64,
            consecutive_failures=1,
        )
        self.error = error
        self.calls = []

    def record_failure(self, task_id, category, failing_tests, *, transient_attempt=1):
        self.calls.append((task_id, category, tuple(failing_tests), transient_attempt))
        if self.error:
            raise self.error
        return self.decision


def test_opt_in_advisor_adds_advice_without_changing_decision(monkeypatch):
    decision = RecoveryDecision(
        action="REPAIR_ONCE", reason="bounded_repair_attempt", task_id="task-1",
        fingerprint="b" * 64, consecutive_failures=1,
    )
    store = FakeStore(decision=decision)
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda *args: AdvisorResult(True, advice="Check the failing test boundary.", reason="advisory_only"),
    )

    result = recovery_ai_local.record_failure_with_local_advice(
        store, "task-1", "test_regression", ["tests/test_example.py"], advisor_enabled=True
    )

    assert result.decision is decision
    assert result.advisor.available is True
    assert result.advisor.advice == "Check the failing test boundary."


def test_advisor_is_not_called_without_explicit_opt_in(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda *args: pytest.fail("advisor must not be called without opt-in"),
    )

    result = recovery_ai_local.record_failure_with_local_advice(
        store, "task-1", "timeout"
    )

    assert result.decision is store.decision
    assert result.advisor.available is False
    assert result.advisor.reason == "advisor_disabled_or_not_applicable"


def test_advisor_error_does_not_change_recovery_decision(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda *args: (_ for _ in ()).throw(RuntimeError("local model unavailable")),
    )

    result = recovery_ai_local.record_failure_with_local_advice(
        store, "task-1", "timeout", advisor_enabled=True
    )

    assert result.decision is store.decision
    assert result.advisor.available is False
    assert result.advisor.reason == "advisor_unexpected_error"


def test_state_persistence_failure_never_calls_advisor(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda *args: pytest.fail("must not call advisor for state persistence failure"),
    )

    result = recovery_ai_local.record_failure_with_local_advice(
        store, "task-1", "state_persistence_failure", advisor_enabled=True
    )

    assert result.decision is store.decision
    assert result.advisor.available is False


def test_state_write_failure_stops_before_advisor(monkeypatch):
    store = FakeStore(error=RecoveryStateError("state write failed"))
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda *args: pytest.fail("must not call advisor after state write failure"),
    )

    with pytest.raises(RecoveryStateError):
        recovery_ai_local.record_failure_with_local_advice(
            store, "task-1", "timeout", advisor_enabled=True
        )


def test_failing_test_iterable_is_materialized_once(monkeypatch):
    store = FakeStore()
    observed = []
    monkeypatch.setattr(
        recovery_ai_local, "advise",
        lambda task_id, category, tests: (
            observed.extend(tests) or AdvisorResult(False, reason="fm_cli_unavailable")
        ),
    )

    result = recovery_ai_local.record_failure_with_local_advice(
        store, "task-1", "timeout", iter(["tests/test_example.py"]), advisor_enabled=True
    )

    assert store.calls[0][2] == ("tests/test_example.py",)
    assert observed == ["tests/test_example.py"]
    assert result.decision is store.decision
