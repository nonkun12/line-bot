from __future__ import annotations

import json
from pathlib import Path

from scripts.replenish_autonomous_task_queue import replenish_queue


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_replenishes_only_when_existing_queue_is_exhausted(tmp_path: Path):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    catalog = tmp_path / "catalog.json"
    _write(queue, {"version": 1, "max_tasks_per_run": 4, "tasks": [{"id": "done-task", "instruction": "x", "allowed_paths": ["tests/test_recovery_ai.py"]}]})
    _write(state, {"completed": []})
    _write(catalog, {"tasks": [{"id": "next-task", "instruction": "test-only", "allowed_paths": ["tests/test_recovery_ai.py"]}]})
    changed, reason = replenish_queue(queue, state, catalog)
    assert changed is False
    assert reason == "queue_not_empty"


def test_adds_only_allowlisted_catalog_tasks_without_duplicates(tmp_path: Path):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    catalog = tmp_path / "catalog.json"
    _write(queue, {"version": 1, "max_tasks_per_run": 4, "tasks": [{"id": "done-task", "instruction": "x", "allowed_paths": ["tests/test_recovery_ai.py"]}]})
    _write(state, {"completed": ["done-task"]})
    _write(catalog, {"tasks": [
        {"id": "done-task", "instruction": "duplicate", "allowed_paths": ["tests/test_recovery_ai.py"]},
        {"id": "next-task", "instruction": "test-only", "allowed_paths": ["tests/test_recovery_ai.py"]},
    ]})
    changed, reason = replenish_queue(queue, state, catalog)
    assert changed is True
    assert reason == "added:next-task"
    assert [t["id"] for t in json.loads(queue.read_text())["tasks"]] == ["done-task", "next-task"]


def test_rejects_catalog_paths_outside_allowlist(tmp_path: Path):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    catalog = tmp_path / "catalog.json"
    _write(queue, {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    _write(state, {"completed": []})
    _write(catalog, {"tasks": [{"id": "unsafe", "instruction": "x", "allowed_paths": [".github/workflows/distributed-autonomous-loop.yml"]}]})
    try:
        replenish_queue(queue, state, catalog)
    except ValueError as exc:
        assert "non-allowlisted" in str(exc)
    else:
        raise AssertionError("expected unsafe path rejection")
