import json
from pathlib import Path

import pytest

from scripts.distributed_loop_execution_approval import authorize_one_task


def _fixtures(tmp_path: Path):
    task = {"id": "approved-task-001", "instruction": "Add one focused regression test.",
            "allowed_paths": ["tests/test_example.py"]}
    queue = tmp_path / "queue.json"
    event = tmp_path / "event.json"
    catalog = tmp_path / "catalog.json"
    queue.write_text(json.dumps({"version": 1, "max_tasks_per_run": 1, "tasks": [task]}))
    catalog.write_text(json.dumps({"version": 1, "tasks": [{**task, "execution_approved": True}]}))
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
    return queue, event, catalog


def _authorize(queue, event, catalog):
    return authorize_one_task(queue, event, catalog, base_sha="a" * 40, ref="refs/heads/main",
                              actor="nonkun12", repository="nonkun12/line-bot")


def test_one_exact_dispatch_approval_is_bound_and_queue_is_reduced(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    result = _authorize(queue, event, catalog)
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
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(event.read_text())
    data["inputs"][field] = value
    event.write_text(json.dumps(data))
    before = queue.read_text()
    with pytest.raises(ValueError):
        _authorize(queue, event, catalog)
    assert queue.read_text() == before


def test_approval_selects_exactly_one_task_from_multi_task_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(queue.read_text())
    data["tasks"].append({**data["tasks"][0], "id": "another-task-002"})
    queue.write_text(json.dumps(data))
    result = _authorize(queue, event, catalog)
    assert result["authorized_task_count"] == 1
    assert [task["id"] for task in json.loads(queue.read_text())["tasks"]] == ["approved-task-001"]


def test_non_dispatch_or_wrong_actor_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    queue, event, catalog = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        _authorize(queue, event, catalog)


def test_invalid_ref_or_repository_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        authorize_one_task(queue, event, catalog, base_sha="a" * 40, ref="refs/heads/feature",
                           actor="nonkun12", repository="nonkun12/line-bot")


def test_unapproved_catalog_task_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(catalog.read_text())
    data["tasks"][0]["execution_approved"] = False
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not_registered_or_not_approved"):
        _authorize(queue, event, catalog)



def test_one_shot_marker_is_consumed_only_by_guarded_runtime():
    root = Path(__file__).resolve().parents[1]
    approval_helper = (root / "scripts/distributed_loop_execution_approval.py").read_text(encoding="utf-8")
    guarded_runtime = (root / "scripts/run_guarded_runtime.py").read_text(encoding="utf-8")
    assert "_consume_execution_approval" not in approval_helper
    assert "consumption = _consume_execution_approval(approval_evidence, start_sha)" in guarded_runtime



def test_cli_requires_and_accepts_catalog_argument(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    env = os.environ.copy()
    env.update({
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "nonkun12",
        "GITHUB_REPOSITORY": "nonkun12/line-bot",
    })
    result = subprocess.run(
        [sys.executable, "-m", "scripts.distributed_loop_execution_approval",
         "--queue", str(queue), "--event", str(event),
         "--catalog", str(catalog), "--base-sha", "a" * 40],
        cwd=Path(__file__).resolve().parents[1],
        env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"status": "PASS"' in result.stdout
    assert "consumption" in result.stdout
