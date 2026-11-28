from pathlib import Path

import pytest

from core.rsi_executor import RSIControl
from core.rsi_runtime import build_rsi_runtime


def _runtime(path: Path, control: RSIControl | None = None):
    control_state = control or RSIControl(
        global_hold=True,
        execution_enabled=False,
        free_only=True,
        budget_known=True,
        budget_remaining_units=0,
        paid_fallback_enabled=False,
    )
    return build_rsi_runtime(
        path,
        control_provider=lambda: control_state,
        verify_approval=lambda _approval: False,
        verify_evaluation=lambda _evaluation: False,
        verify_evidence_signature=lambda _producer, _digest, _signature: False,
        executor_id="rsi-runtime-test",
    )


def test_runtime_uses_one_durable_ledger_for_executor_and_stage165(tmp_path):
    ledger_path = (tmp_path / "rsi" / "evidence.sqlite").resolve()
    ledger_path.parent.mkdir()
    runtime = _runtime(ledger_path)

    assert runtime.ledger.path == str(ledger_path)
    assert runtime.executor.ledger is runtime.ledger
    assert runtime.recursive_feedback._ledger is runtime.ledger
    assert runtime.verify_evidence_integrity() is True

    restarted = _runtime(ledger_path)
    assert restarted.ledger.path == runtime.ledger.path
    assert restarted.verify_evidence_integrity() is True


def test_runtime_rejects_ephemeral_or_relative_ledger_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        _runtime(Path("relative.sqlite"))
    with pytest.raises(ValueError, match="durable"):
        _runtime(Path(":memory:"))


def test_runtime_does_not_release_hold_or_enable_execution(tmp_path):
    control = RSIControl(
        global_hold=True,
        execution_enabled=False,
        free_only=True,
        budget_known=True,
        budget_remaining_units=0,
        paid_fallback_enabled=False,
    )
    runtime = _runtime((tmp_path / "evidence.sqlite").resolve(), control)

    assert control.global_hold is True
    assert control.execution_enabled is False
    assert runtime.executor.ledger is runtime.ledger
