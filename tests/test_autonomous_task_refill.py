from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.autonomous_task_refill import build_queue


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _task(task_id: str) -> dict:
    return {"id": task_id, "instruction": "Run a focused regression test.", "allowed_paths": ["tests/test_example.py"]}


def test_refill_adds_only_uncompleted_catalog_tasks_within_cap(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": [_task("task-existing")]})
    catalog = _write(tmp_path / "catalog.json", {"version": 1, "max_additions_per_run": 2, "tasks": [_task("task-new-one"), _task("task-new-two"), _task("task-new-three")]})
    completed = _write(tmp_path / "state.json", {"version": 1, "completed": ["task-new-two"]})
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, completed, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    ids = [task["id"] for task in result["tasks"]]
    assert report["added"] == 2
    assert ids == ["task-existing", "task-new-one", "task-new-three"]
    assert not queue.read_text(encoding="utf-8") == output.read_text(encoding="utf-8")


def test_refill_fails_closed_on_unsafe_path(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    catalog = _write(tmp_path / "catalog.json", {"version": 1, "max_additions_per_run": 4, "tasks": [{**_task("task-unsafe"), "allowed_paths": ["../secret.txt"]}]})
    completed = _write(tmp_path / "state.json", {"version": 1, "completed": []})

    with pytest.raises(ValueError, match="forbidden"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_refill_rejects_duplicate_catalog_ids(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    catalog = _write(tmp_path / "catalog.json", {"version": 1, "max_additions_per_run": 4, "tasks": [_task("task-same"), _task("task-same")]})
    completed = _write(tmp_path / "state.json", {"version": 1, "completed": []})

    with pytest.raises(ValueError, match="duplicate"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")
