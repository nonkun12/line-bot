"""Regression tests for held catalog tasks hidden by an empty runtime queue."""
import json

import pytest

from scripts import run_minimal_autonomous_loop as loop
from scripts.recovery_ai import RecoveryStore
from scripts.resume_held_task import resume_task


def _task(task_id):
    return {"id": task_id, "instruction": "test", "allowed_paths": ["tests/test_loop_held_stall_and_catalog_resume.py"]}


def test_pending_state_helper_is_read_only_and_fails_closed(tmp_path):
    path = tmp_path / "recovery.json"
    RecoveryStore(path).record_failure("held", "unknown")
    before = path.read_bytes()
    blocked, eligible = loop.pending_registered_task_state(
        [_task("held"), _task("free"), _task("done")], {"done"}, RecoveryStore(path)
    )
    assert blocked == ["held"]
    assert eligible == ["free"]
    assert path.read_bytes() == before


def test_catalog_only_task_resumes_with_confirmation_and_review_gate(tmp_path):
    recovery = tmp_path / "recovery.json"
    store = RecoveryStore(recovery)
    store.record_failure("catalog-task", "unknown")
    store.record_failure("other-task", "unknown")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": [], "recovery_ai": json.loads(recovery.read_text())}), encoding="utf-8")
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": [_task("queued-task")]}), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [_task("catalog-task"), _task("other-task")]}), encoding="utf-8")
    with pytest.raises(ValueError, match="cause is fixed"):
        resume_task(state_path=state, recovery_path=recovery, queue_path=queue, task_id="catalog-task", cause_fixed=False, catalog_path=catalog)
    assert RecoveryStore(recovery).task_status("catalog-task")["held"] is True
    result = resume_task(state_path=state, recovery_path=recovery, queue_path=queue, task_id="catalog-task", cause_fixed=True, catalog_path=catalog)
    assert result == {"task_id": "catalog-task", "held": False, "resume_requires_review": True}
    assert RecoveryStore(recovery).task_status("other-task")["held"] is True


def test_catalog_resume_rejects_duplicate_registration(tmp_path):
    recovery = tmp_path / "recovery.json"
    RecoveryStore(recovery).record_failure("catalog-task", "unknown")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": [], "recovery_ai": json.loads(recovery.read_text())}), encoding="utf-8")
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [_task("catalog-task"), _task("catalog-task")]}), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one queued task"):
        resume_task(state_path=state, recovery_path=recovery, queue_path=queue, task_id="catalog-task", cause_fixed=True, catalog_path=catalog)


def test_catalog_resume_rejects_completed_task(tmp_path):
    recovery = tmp_path / "recovery.json"
    RecoveryStore(recovery).record_failure("catalog-task", "unknown")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": ["catalog-task"], "recovery_ai": json.loads(recovery.read_text())}), encoding="utf-8")
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [_task("catalog-task")]}), encoding="utf-8")
    with pytest.raises(ValueError, match="completed tasks cannot be resumed"):
        resume_task(state_path=state, recovery_path=recovery, queue_path=queue, task_id="catalog-task", cause_fixed=True, catalog_path=catalog)
