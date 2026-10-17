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


def _inputs(tmp_path: Path, *, max_tasks=4, existing=None, candidates=None):
    queue = _write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": max_tasks, "tasks": existing or []})
    catalog = _write(tmp_path / "catalog.json", {"version": 1, "max_additions_per_run": 2, "tasks": candidates or []})
    completed = _write(tmp_path / "state.json", {"version": 1, "completed": []})
    return queue, catalog, completed


def test_refill_adds_only_uncompleted_catalog_tasks_within_cap(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-existing")],
        candidates=[_task("task-new-one"), _task("task-new-two"), _task("task-new-three")],
    )
    state = _write(tmp_path / "state.json", {"version": 1, "completed": ["task-new-two"]})
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, state, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    ids = [task["id"] for task in result["tasks"]]
    assert report["added"] == 2
    assert ids == ["task-existing", "task-new-one", "task-new-three"]
    assert queue.read_text(encoding="utf-8") != output.read_text(encoding="utf-8")


def test_refill_caps_additions_to_remaining_queue_capacity(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        max_tasks=4,
        existing=[_task("task-existing-one"), _task("task-existing-two"), _task("task-existing-three")],
        candidates=[_task("task-new-one"), _task("task-new-two")],
    )
    output = tmp_path / "runtime.json"

    report = build_queue(queue, catalog, completed, output)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert report["added"] == 1
    assert report["total"] == 4
    assert len(result["tasks"]) == 4


def test_refill_rejects_existing_queue_over_limit(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        max_tasks=1,
        existing=[_task("task-existing-one"), _task("task-existing-two")],
        candidates=[_task("task-new-one")],
    )
    with pytest.raises(ValueError, match="existing queue exceeds max_tasks_per_run"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize("max_tasks", [0, -1, 5, "4", True, 1.5])
def test_refill_rejects_invalid_runtime_task_limit(tmp_path: Path, max_tasks):
    queue, catalog, completed = _inputs(tmp_path, max_tasks=max_tasks, candidates=[_task("task-new-one")])
    with pytest.raises(ValueError, match="max_tasks_per_run"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_refill_fails_closed_on_unsafe_path(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-unsafe"), "allowed_paths": ["../secret.txt"]}],
    )
    with pytest.raises(ValueError, match="forbidden"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize(
    "path",
    [
        "tests//test_example.py",
        "./tests/test_example.py",
        "tests/../secret.py",
        "C:/secret.py",
        "c:relative-secret.py",
        "tests/\\x00bad.py",
        "tests/\x00bad.py",
    ],
)
def test_refill_rejects_ambiguous_or_traversal_paths(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    with pytest.raises(ValueError, match="allowed path"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize(
    "path",
    [
        "../tests/test_a.py",
        "tests/../core/x.py",
        "core/ai_speaker.py",
        "scripts/x.py",
        ".github/autonomous-loop-tasks.json",
        "tests/helper.py",
        "tests/test_a.txt",
        "tests/sub/test_a.py",
        "tests",
        "TESTS/test_a.py",
        "tests/test_a.py ",
        "tests//test_a.py",
        "./tests/test_a.py",
        "uhip/tests/sub/test_a.py",
    ],
)
def test_refill_rejects_every_non_allowlisted_path(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    with pytest.raises(ValueError, match="forbidden allowed path"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


@pytest.mark.parametrize("path", ["tests/test_a.py", "uhip/tests/test_a.py"])
def test_refill_accepts_only_allowlisted_test_files(tmp_path: Path, path: str):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[{**_task("task-path"), "allowed_paths": [path]}],
    )
    build_queue(queue, catalog, completed, tmp_path / "runtime.json")
    result = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    assert result["tasks"][0]["allowed_paths"] == [path]


def test_refill_rejects_duplicate_catalog_ids(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        candidates=[_task("task-same"), _task("task-same")],
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_refill_rejects_duplicate_existing_queue_ids(tmp_path: Path):
    queue, catalog, completed = _inputs(
        tmp_path,
        existing=[_task("task-same"), _task("task-same")],
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(queue, catalog, completed, tmp_path / "runtime.json")


def test_repository_catalog_uses_registered_deterministic_tasks():
    """Catalog refill must never enqueue tasks without a deterministic handler."""
    import json

    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS

    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / ".github" / "autonomous-loop-task-catalog.json").read_text(encoding="utf-8"))
    assert isinstance(catalog.get("tasks"), list)
    assert catalog["tasks"], "catalog must retain useful refill candidates"
    for task in catalog["tasks"]:
        assert task["id"] in _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS, task["id"]
        expected_target = _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[task["id"]]
        assert task["allowed_paths"] == [expected_target], task["id"]
