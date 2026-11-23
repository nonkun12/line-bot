import json
from pathlib import Path

import pytest

from scripts import confirm_machine_resume_review as module


def _inputs(tmp_path):
    task = {
        "id": "machine-task-1",
        "instruction": "Run a bounded test and verify with REA.",
        "allowed_paths": ["tests/test_example.py"],
        "execution_approved": True,
        "resume_policy": "machine_evidence",
    }
    import hashlib
    paths_sha = hashlib.sha256(b'["tests/test_example.py"]').hexdigest()
    instruction_sha = hashlib.sha256(task["instruction"].encode()).hexdigest()
    evidence = {
        "schema_version": 1,
        "task_id": task["id"],
        "instruction_sha256": instruction_sha,
        "allowed_paths_sha256": paths_sha,
        "base_sha": "a" * 40,
        "target_sha": "b" * 40,
        "evaluated_paths": ["tests/test_example.py"],
        "scanner_complete": True,
        "scanner_status": "PASS",
        "tests_status": "PASS",
        "tests_exit_code": 0,
        "cause_status": "FIXED",
        "cause_evidence_sha256": "c" * 64,
        "workflow_run_id": "123456789",
        "run_attempt": 1,
        "created_at": "2026-11-23T03:00:00+00:00",
        "nonce": "d" * 32,
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
    state = tmp_path / "state.json"
    recovery = {
        "schema_version": 1,
        "checkpoint": None,
        "tasks": {
            task["id"]: {
                "held": False,
                "resume_requires_review": True,
            }
        },
    }
    state.write_text(json.dumps({
        "version": 1,
        "completed": [],
        "recovery_ai": recovery,
    }), encoding="utf-8")
    recovery_file = tmp_path / "recovery.json"
    recovery_file.write_text(json.dumps(recovery), encoding="utf-8")
    return task, catalog, evidence_file, state, recovery_file


def _run(tmp_path, **overrides):
    _, catalog, evidence, state, recovery = _inputs(tmp_path)
    args = {
        "state_file": state,
        "recovery_state_file": recovery,
        "catalog_file": catalog,
        "evidence_file": evidence,
        "task_id": "machine-task-1",
        "expected_base_sha": "a" * 40,
        "expected_workflow_run_id": "123456789",
        "expected_run_attempt": 1,
        "expected_nonce": "d" * 32,
    }
    args.update(overrides)
    return module.confirm_if_machine_verified(**args), state, recovery


def test_confirm_only_after_machine_evidence_passes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "confirm_in_durable_state", lambda *args: calls.append(args))
    result, _, _ = _run(tmp_path)
    assert result["status"] == "PASS"
    assert len(calls) == 1


def test_invalid_nonce_does_not_confirm_or_mutate_state(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "confirm_in_durable_state", lambda *args: calls.append(args))
    _, _, evidence, state, recovery = _inputs(tmp_path)
    before_state = state.read_bytes()
    before_recovery = recovery.read_bytes()
    with pytest.raises(ValueError, match="resume_evidence_binding_or_gate_failed"):
        module.confirm_if_machine_verified(
            state_file=state,
            recovery_state_file=recovery,
            catalog_file=tmp_path / "catalog.json",
            evidence_file=evidence,
            task_id="machine-task-1",
            expected_base_sha="a" * 40,
            expected_workflow_run_id="123456789",
            expected_run_attempt=1,
            expected_nonce="e" * 32,
        )
    assert calls == []
    assert state.read_bytes() == before_state
    assert recovery.read_bytes() == before_recovery


def test_held_task_cannot_be_confirmed_by_review_evidence(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "confirm_in_durable_state", lambda *args: calls.append(args))
    _, catalog, evidence, state, recovery = _inputs(tmp_path)
    payload = json.loads(state.read_text())
    payload["recovery_ai"]["tasks"]["machine-task-1"]["held"] = True
    state.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="resume_task_not_pending_machine_review"):
        module.confirm_if_machine_verified(
            state_file=state,
            recovery_state_file=recovery,
            catalog_file=catalog,
            evidence_file=evidence,
            task_id="machine-task-1",
            expected_base_sha="a" * 40,
            expected_workflow_run_id="123456789",
            expected_run_attempt=1,
            expected_nonce="d" * 32,
        )
    assert calls == []


def test_human_review_task_is_not_machine_eligible(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "confirm_in_durable_state", lambda *args: calls.append(args))
    _, catalog, evidence, state, recovery = _inputs(tmp_path)
    task_data = json.loads(catalog.read_text())
    task_data["tasks"][0]["instruction"] = "人手レビュー後に実行する"
    catalog.write_text(json.dumps(task_data))
    with pytest.raises(ValueError, match="resume_task_requires_human_review"):
        module.confirm_if_machine_verified(
            state_file=state,
            recovery_state_file=recovery,
            catalog_file=catalog,
            evidence_file=evidence,
            task_id="machine-task-1",
            expected_base_sha="a" * 40,
            expected_workflow_run_id="123456789",
            expected_run_attempt=1,
            expected_nonce="d" * 32,
        )
    assert calls == []
