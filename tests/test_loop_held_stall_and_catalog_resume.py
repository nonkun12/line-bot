""""Regression tests for held catalog tasks hidden by an empty runtime queue."""
import json
from types import SimpleNamespace

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


def test_held_stall_record_is_auditable_and_not_a_completion():
    record = loop.held_stall_record(
        [_task("done"), _task("held-a"), _task("held-b")],
        {"done"},
        ["held-a", "held-b"],
        [],
    )
    assert record["status"] == "BLOCKED"
    assert record["failure_reason"] == "all_pending_tasks_held"
    assert record["queue_total"] == 3
    assert record["queue_completed"] == 1
    assert record["held_pending_count"] == 2
    assert record["eligible_pending_count"] == 0
    assert record["task_count"] == 0
    assert record["exit_code"] == 79


def test_held_stall_record_rejects_eligible_task():
    with pytest.raises(ValueError, match="no eligible tasks"):
        loop.held_stall_record(
            [_task("held"), _task("free")],
            set(),
            ["held"],
            ["free"],
        )


def test_main_records_blocked_when_runtime_queue_is_empty_and_catalog_tasks_are_held(tmp_path, monkeypatch, capsys):
    """Exercise main's real empty-queue branch; it must not report NOT_RUN as green."""
    import sys

    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"tasks": [], "max_tasks_per_run": 3}), encoding="utf-8")
    results_path = tmp_path / "results.jsonl"
    state_path = tmp_path / "state.json"
    recovery_path = tmp_path / "recovery-ai-state.json"
    store = RecoveryStore(recovery_path)
    catalog = [_task("held-a"), _task("held-b")]
    for task in catalog:
        store.record_failure(task["id"], "unknown")

    monkeypatch.setattr(loop, "QUEUE", queue_path)
    monkeypatch.setattr(loop, "_git_head", lambda: "a" * 40)
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: catalog)
    monkeypatch.setattr(loop.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["run_minimal_autonomous_loop.py", "--results", str(results_path), "--state", str(state_path)])

    import core.control_tower_selector as selector
    monkeypatch.setattr(selector, "select_next_task", lambda *_args, **_kwargs: SimpleNamespace(next_action="NOT_RUN", reason_code="queue_empty"))

    exit_code = loop.main()

    assert exit_code == 79
    lines = results_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status"] == "BLOCKED"
    assert record["failure_reason"] == "all_pending_tasks_held"
    assert record["held_pending_count"] == 2
    assert record["eligible_pending_count"] == 0
    assert "MINIMAL_LOOP=BLOCKED reason=all_pending_tasks_held" in capsys.readouterr().out
