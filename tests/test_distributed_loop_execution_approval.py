import json
from pathlib import Path

import pytest

from scripts.distributed_loop_execution_approval import authorize_one_task


def _fixtures(tmp_path: Path):
    task = {"id": "approved-task-001", "instruction": "Add one focused regression test.",
            "allowed_paths": ["tests/test_example.py"]}
    queue = tmp_path / "queue.json"
    event = tmp_path / "event.json"
    queue.write_text(json.dumps({"version": 1, "max_tasks_per_run": 1, "tasks": [task]}))
    event.write_text(json.dumps({
        "sender": {"login": "nonkun12"},
        "repository": {"full_name": "nonkun12/line-bot"},
        "inputs": {
            "execution_approval": "APPROVE_EXECUTION", "mode": "normal",
            "approval_task_id": task["id"],
            "approval_instruction_sha256": __import__("hashlib").sha256(task["instruction"].encode()).hexdigest(),
            "approval_allowed_paths_sha256": __import__("hashlib").sha256(
                json.dumps(task["allowed_paths"], separators=(",", ":")).encode()
            ).hexdigest(),
            "approval_base_sha": "a" * 40,
        },
    }))
    return queue, event


def _authorize(queue, event):
    return authorize_one_task(queue, event, base_sha="a" * 40, ref="refs/heads/main",
                              actor="nonkun12", repository="nonkun12/line-bot")


def test_one_exact_dispatch_approval_is_bound_and_queue_is_reduced(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event = _fixtures(tmp_path)
    result = _authorize(queue, event)
    assert result["status"] == "PASS"
    assert result["authorized_task_count"] == 1
    assert json.loads(queue.read_text())["tasks"][0]["id"] == "approved-task-001"


@pytest.mark.parametrize("field,value", [
    ("approval_task_id", "different-task-001"),
    ("approval_instruction_sha256", "0" * 64),
    ("approval_allowed_paths_sha256", "0" * 64),
    ("approval_base_sha", "b" * 40),
    ("execution_approval", "DENY"),
])
def test_mismatched_or_denied_dispatch_fails_closed(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event = _fixtures(tmp_path)
    data = json.loads(event.read_text())
    data["inputs"][field] = value
    event.write_text(json.dumps(data))
    before = queue.read_text()
    with pytest.raises(ValueError):
        _authorize(queue, event)
    assert queue.read_text() == before


def test_queue_with_multiple_tasks_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event = _fixtures(tmp_path)
    data = json.loads(queue.read_text())
    data["tasks"].append({**data["tasks"][0], "id": "another-task-002"})
    queue.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="exactly_one"):
        _authorize(queue, event)


def test_non_dispatch_or_wrong_actor_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    queue, event = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        _authorize(queue, event)


def test_invalid_ref_or_repository_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        authorize_one_task(queue, event, base_sha="a" * 40, ref="refs/heads/feature",
                           actor="nonkun12", repository="nonkun12/line-bot")
