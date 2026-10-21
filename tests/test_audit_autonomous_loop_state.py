from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_autonomous_loop_state import audit_queue_state, main


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _evidence(tmp_path: Path, queue_tasks, completed=(), recovery_tasks=None):
    recovery_data = {
        "schema_version": 1,
        "tasks": recovery_tasks or {},
        "checkpoint": None,
    }
    queue = _write(tmp_path / "queue.json", {"tasks": queue_tasks})
    state = _write(tmp_path / "state.json", {
        "version": 1,
        "completed": list(completed),
        "recovery_ai": recovery_data,
    })
    recovery = _write(tmp_path / "recovery.json", recovery_data)
    return queue, state, recovery


def test_audit_reports_pending_and_held_without_mutating_any_input(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path,
        [{"id": "task-one"}, {"id": "task-two"}],
        completed=["task-one", "old-task"],
        recovery_tasks={"task-two": {
            "held": True, "last_category": "timeout", "consecutive_failures": 3
        }},
    )
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (queue, state, recovery)}

    report = audit_queue_state(queue, state, recovery)

    assert report["status"] == "BLOCKED"
    assert report["all_pending_held"] is True
    assert report["pending_task_ids"] == ["task-two"]
    assert report["held_pending"] == [{
        "task_id": "task-two", "last_category": "timeout", "consecutive_failures": 3
    }]
    assert report["stale_completed_ids"] == ["old-task"]
    assert "stale_completed_ids" in report["warnings"]
    assert report["writes_attempted"] == 0
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (queue, state, recovery)} == before


def test_missing_recovery_copy_fails_closed(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "one"}, {"id": "two"}]})
    state = _write(tmp_path / "state.json", {"version": 1, "completed": []})
    recovery = _write(tmp_path / "recovery.json", {
        "schema_version": 1, "tasks": {"two": {"held": True}}, "checkpoint": None
    })

    with pytest.raises(ValueError, match="recovery_state_missing"):
        audit_queue_state(queue, state, recovery)


def test_recovery_file_must_match_durable_copy(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "task"}], recovery_tasks={"task": {"held": True}}
    )
    recovery.write_text(json.dumps({
        "schema_version": 1, "tasks": {}, "checkpoint": None
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="recovery_state_mismatch"):
        audit_queue_state(queue, state, recovery)


def test_partial_hold_is_warning_not_runner_stop(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "held"}, {"id": "ready"}],
        recovery_tasks={"held": {"held": True, "last_category": "timeout"}},
    )
    report = audit_queue_state(queue, state, recovery)
    assert report["status"] == "WARN"
    assert report["all_pending_held"] is False
    assert report["held_pending_count"] == 1


def test_held_completed_task_is_reported(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "done"}], completed=["done"],
        recovery_tasks={"done": {"held": True}},
    )
    report = audit_queue_state(queue, state, recovery)
    assert report["status"] == "COMPLETED"
    assert report["held_completed_task_ids"] == ["done"]
    assert "held_completed_tasks" in report["warnings"]


def test_resumed_task_waiting_for_review_is_reported(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "resumed"}],
        recovery_tasks={"resumed": {"held": False, "resume_requires_review": True}},
    )
    report = audit_queue_state(queue, state, recovery)
    assert report["status"] == "OK"
    assert report["resume_requires_review_task_ids"] == ["resumed"]
    assert "resume_requires_review" in report["warnings"]


def test_empty_queue_and_all_completed_are_not_reported_as_plain_ok(tmp_path: Path):
    queue, state, recovery = _evidence(tmp_path, [])
    report = audit_queue_state(queue, state, recovery)
    assert report["status"] == "NOT_RUN"
    assert "empty_queue" in report["warnings"]

    queue, state, recovery = _evidence(
        tmp_path, [{"id": "done"}], completed=["done"]
    )
    report = audit_queue_state(queue, state, recovery)
    assert report["status"] == "COMPLETED"
    assert "all_tasks_completed" in report["warnings"]


def test_duplicate_completed_ids_are_reported(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "done"}], completed=["done", "done"]
    )
    report = audit_queue_state(queue, state, recovery)
    assert report["duplicate_completed_ids"] == ["done"]
    assert "duplicate_completed_ids" in report["warnings"]


def test_audit_rejects_duplicate_queue_ids(tmp_path: Path):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "same"}, {"id": "same"}]
    )
    with pytest.raises(ValueError, match="duplicate_queue_task_id"):
        audit_queue_state(queue, state, recovery)


def test_audit_fails_closed_on_invalid_state_schema(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task"}]})
    state = _write(tmp_path / "state.json", {"completed": []})
    recovery = _write(tmp_path / "recovery.json", {
        "schema_version": 1, "tasks": {}, "checkpoint": None
    })
    with pytest.raises(ValueError, match="invalid_state_schema"):
        audit_queue_state(queue, state, recovery)


def test_cli_returns_blocked_for_all_held_tasks(tmp_path: Path, monkeypatch, capsys):
    queue, state, recovery = _evidence(
        tmp_path, [{"id": "task"}],
        recovery_tasks={"task": {"held": True, "last_category": "unknown"}},
    )
    monkeypatch.setattr("sys.argv", [
        "audit_autonomous_loop_state", "--queue", str(queue),
        "--state", str(state), "--recovery", str(recovery),
    ])
    assert main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["held_pending_count"] == 1


def test_cli_fails_closed_on_deeply_nested_queue_shape(tmp_path: Path, monkeypatch, capsys):
    queue = tmp_path / "queue.json"
    queue.write_text('{"tasks":' + "[" * 5000 + "0" + "]" * 5000 + "}", encoding="utf-8")
    state = _write(tmp_path / "state.json", {
        "version": 1, "completed": [],
        "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None},
    })
    recovery = _write(tmp_path / "recovery.json", {
        "schema_version": 1, "tasks": {}, "checkpoint": None
    })
    monkeypatch.setattr("sys.argv", [
        "audit_autonomous_loop_state", "--queue", str(queue),
        "--state", str(state), "--recovery", str(recovery),
    ])
    assert main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["reason"] == "invalid_queue_task"


def test_cli_returns_not_run_exit_code_for_empty_queue(tmp_path: Path, monkeypatch, capsys):
    queue, state, recovery = _evidence(tmp_path, [])
    monkeypatch.setattr("sys.argv", [
        "audit_autonomous_loop_state", "--queue", str(queue),
        "--state", str(state), "--recovery", str(recovery),
    ])
    assert main() == 78
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "NOT_RUN"
    assert "empty_queue" in output["warnings"]
