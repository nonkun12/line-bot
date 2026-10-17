from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_autonomous_loop_state import audit_queue_state, main


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_audit_reports_pending_and_held_without_mutating_state(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-one"}, {"id": "task-two"}]})
    state_data = {
        "completed": ["task-one", "old-task"],
        "recovery_ai": {"tasks": {"task-two": {
            "held": True, "last_category": "timeout", "consecutive_failures": 3
        }}},
    }
    state = _write(tmp_path / "state.json", state_data)

    report = audit_queue_state(queue, state)

    assert report["status"] == "BLOCKED"
    assert report["queue_total"] == 2
    assert report["completed_in_queue"] == 1
    assert report["pending_task_ids"] == ["task-two"]
    assert report["held_pending"] == [{
        "task_id": "task-two", "last_category": "timeout", "consecutive_failures": 3
    }]
    assert report["stale_completed_ids"] == ["old-task"]
    assert report["state_mutated"] is False
    assert json.loads(state.read_text(encoding="utf-8")) == state_data


def test_audit_allows_old_completed_ids_but_counts_them_separately(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-one"}]})
    state = _write(tmp_path / "state.json", {"completed": ["task-one", "old-task"]})

    report = audit_queue_state(queue, state)

    assert report["status"] == "OK"
    assert report["completed_in_queue"] == 1
    assert report["stale_completed_count"] == 1
    assert report["held_pending_count"] == 0


def test_audit_rejects_duplicate_queue_ids(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "same-task"}, {"id": "same-task"}]})
    state = _write(tmp_path / "state.json", {"completed": []})

    with pytest.raises(ValueError, match="duplicate_queue_task_id"):
        audit_queue_state(queue, state)


def test_audit_fails_closed_on_invalid_state(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-one"}]})
    state = _write(tmp_path / "state.json", {"completed": "not-a-list"})

    with pytest.raises(ValueError, match="invalid_completed_state"):
        audit_queue_state(queue, state)


def test_cli_returns_blocked_for_held_pending_task(tmp_path: Path, monkeypatch, capsys):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-one"}]})
    state = _write(tmp_path / "state.json", {
        "completed": [],
        "recovery_ai": {"tasks": {"task-one": {"held": True, "last_category": "unknown"}}},
    })
    monkeypatch.setattr("sys.argv", ["audit_autonomous_loop_state", "--queue", str(queue), "--state", str(state)])

    assert main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["held_pending_count"] == 1
