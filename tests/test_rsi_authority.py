from __future__ import annotations

import hashlib
import json

import pytest

from core.rsi_authority import build_rsi_authority
from scripts.recovery_ai import RecoveryStore


def _build(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "rsi-task-01")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return build_rsi_authority(
        experiment_id="rsi-exp-01",
        start_sha="a" * 40,
        instruction="Run bounded local RSI. RSI_EXPERIMENT_ID=rsi-exp-01",
        recovery_state_path=tmp_path / "recovery-ai-state.json",
    )


def test_approval_is_bound_to_experiment_and_consumed_once(tmp_path, monkeypatch):
    from scripts import run_guarded_runtime

    verify_calls = []
    consume_calls = []
    evidence = {
        "gate": "PASS",
        "execution_authorized": True,
        "task_id": "rsi-task-01",
        "base_sha": "a" * 40,
        "instruction_sha256": "b" * 64,
        "allowed_paths_sha256": "c" * 64,
        "actor": "nonkun12",
    }
    monkeypatch.setattr(run_guarded_runtime, "_verify_execution_approval", lambda sha, instruction: verify_calls.append((sha, instruction)) or dict(evidence))
    monkeypatch.setattr(run_guarded_runtime, "_consume_execution_approval", lambda approval, sha: consume_calls.append((approval, sha)) or {"gate": "PASS"})
    approval, _safety = _build(tmp_path, monkeypatch)

    assert approval("rsi-exp-01") is True
    assert approval("rsi-exp-01") is True
    assert approval("other-experiment") is False
    assert len(verify_calls) == 2
    assert len(consume_calls) == 1


def test_approval_fails_closed_when_task_identity_changes(tmp_path, monkeypatch):
    from scripts import run_guarded_runtime

    monkeypatch.setattr(
        run_guarded_runtime,
        "_verify_execution_approval",
        lambda *_args: {
            "gate": "PASS",
            "execution_authorized": True,
            "task_id": "rsi-task-01",
            "base_sha": "a" * 40,
            "instruction_sha256": "b" * 64,
            "allowed_paths_sha256": "c" * 64,
            "actor": "nonkun12",
        },
    )
    monkeypatch.setattr(run_guarded_runtime, "_consume_execution_approval", lambda *_args: {"gate": "PASS"})
    approval, _safety = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "different-task")

    assert approval("rsi-exp-01") is False


def test_safety_provider_uses_shared_stop_and_recovery_store(tmp_path, monkeypatch):
    import core.emergency_stop as emergency_stop

    monkeypatch.setattr(emergency_stop, "local_stop_active", lambda _root: False)
    monkeypatch.setattr(emergency_stop, "get_status", lambda _repo, _token: False)
    _approval, safety = _build(tmp_path, monkeypatch)

    snapshot = safety()
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    expected = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert snapshot["stop_state"] == "INACTIVE"
    assert snapshot["global_hold_state"] == "CLEAR"
    assert snapshot["snapshot_sha256"] == expected


def test_safety_provider_blocks_if_any_recovery_task_is_held(tmp_path, monkeypatch):
    import core.emergency_stop as emergency_stop

    monkeypatch.setattr(emergency_stop, "local_stop_active", lambda _root: False)
    monkeypatch.setattr(emergency_stop, "get_status", lambda _repo, _token: False)
    store = RecoveryStore(tmp_path / "recovery-ai-state.json")
    store.record_failure("held-task", "test_regression", ["test.one"])
    store.record_failure("held-task", "test_regression", ["test.two"])
    store.record_failure("held-task", "test_regression", ["test.three"])

    _approval, safety = _build(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="recovery_global_hold_active"):
        safety()


def test_safety_provider_blocks_if_shared_stop_is_active(tmp_path, monkeypatch):
    import core.emergency_stop as emergency_stop

    monkeypatch.setattr(emergency_stop, "local_stop_active", lambda _root: False)
    monkeypatch.setattr(emergency_stop, "get_status", lambda _repo, _token: True)
    _approval, safety = _build(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="shared_emergency_stop_active"):
        safety()


def test_safety_provider_blocks_when_shared_stop_cannot_be_checked(tmp_path, monkeypatch):
    import core.emergency_stop as emergency_stop

    monkeypatch.setattr(emergency_stop, "local_stop_active", lambda _root: False)

    def unavailable(*_args):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(emergency_stop, "get_status", unavailable)
    _approval, safety = _build(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="network unavailable"):
        safety()


def test_builder_requires_experiment_id_in_human_approved_instruction(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "rsi-task-01")
    with pytest.raises(ValueError, match="not_bound_to_approved_instruction"):
        build_rsi_authority(
            experiment_id="rsi-exp-01",
            start_sha="a" * 40,
            instruction="Run RSI without binding its experiment identity.",
            recovery_state_path=tmp_path / "state.json",
        )
