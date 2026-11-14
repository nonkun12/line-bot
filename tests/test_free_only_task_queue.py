import json
from pathlib import Path

import pytest

from scripts.free_only_task_queue import filter_queue


def _write_queue(path: Path, tasks):
    path.write_text(
        json.dumps({"version": 1, "max_tasks_per_run": 4, "tasks": tasks}),
        encoding="utf-8",
    )


def _task(task_id="router-regression-english-casefold", paths=None):
    return {
        "id": task_id,
        "instruction": "指定テストに回帰テストを1件追加する。",
        "allowed_paths": paths or ["tests/test_management_router.py"],
    }


def test_filter_queue_keeps_only_exact_registered_deterministic_tasks(tmp_path):
    source = tmp_path / "queue.json"
    output = tmp_path / "free-queue.json"
    report = tmp_path / "report.json"
    _write_queue(source, [
        _task("router-regression-english-casefold"),
        _task("review-coverage-gap-703fa3c06b", ["tests/test_project_registry.py"]),
        _task("model-backed-task", ["tests/test_project_registry.py"]),
        _task("router-regression-whitespace", ["tests/test_recovery_ai.py"]),
    ])

    result = filter_queue(source, output, report)

    queued = json.loads(output.read_text(encoding="utf-8"))
    assert [task["id"] for task in queued["tasks"]] == ["router-regression-english-casefold"]
    assert result["eligible_deterministic_count"] == 1
    assert result["excluded_count"] == 3
    assert {item["reason"] for item in result["excluded_tasks"]} == {
        "not_registered_deterministic",
        "registered_path_mismatch",
        "review_gap_requires_model",
    }


def test_filter_queue_writes_empty_queue_and_explicit_report_when_no_task_is_free(tmp_path):
    source, output, report = (tmp_path / name for name in ("queue.json", "free.json", "report.json"))
    _write_queue(source, [_task("model-backed-task", ["tests/test_project_registry.py"])])

    result = filter_queue(source, output, report)

    assert result["status"] == "NO_DETERMINISTIC_TASKS"
    assert result["eligible_deterministic_count"] == 0
    assert json.loads(output.read_text(encoding="utf-8"))["tasks"] == []


@pytest.mark.parametrize("payload", [
    [],
    {"version": True, "max_tasks_per_run": 1, "tasks": []},
    {"version": 1, "max_tasks_per_run": 0, "tasks": []},
    {"version": 1, "max_tasks_per_run": 1, "tasks": {}},
])
def test_filter_queue_rejects_invalid_queue_envelope(tmp_path, payload):
    source, output, report = (tmp_path / name for name in ("queue.json", "free.json", "report.json"))
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        filter_queue(source, output, report)


def test_filter_queue_rejects_duplicate_task_ids(tmp_path):
    source, output, report = (tmp_path / name for name in ("queue.json", "free.json", "report.json"))
    _write_queue(source, [_task(), _task()])

    with pytest.raises(ValueError, match="duplicate"):
        filter_queue(source, output, report)


def test_filter_queue_never_overwrites_its_input(tmp_path):
    source = tmp_path / "queue.json"
    _write_queue(source, [_task()])

    with pytest.raises(ValueError, match="must differ"):
        filter_queue(source, source, tmp_path / "report.json")
