from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.distributed_ai_event_ledger import build_event_ledger


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_records_assignment_start_and_verified_completion(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {
        "tasks": [{"id": "task-alpha", "allowed_paths": ["tests/test_alpha.py"]}]
    })
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({
        "task_id": "task-alpha", "status": "PASS",
        "test_summary": "1 passed", "artifact": "patch.diff",
    }) + "\n", encoding="utf-8")
    output = tmp_path / "events.jsonl"

    report = build_event_ledger(queue, results, output, "run-123")
    events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert report["event_count"] == 3
    assert [event["event_type"] for event in events] == [
        "task.assigned", "task.started", "task.completed"
    ]
    assert events[-1]["actor"] == "verifier"
    assert events[-1]["details"] == {
        "status": "PASS", "has_test_evidence": True, "has_artifact_evidence": True
    }
    assert len({event["event_id"] for event in events}) == 3


@pytest.mark.parametrize(("status", "expected"), [
    ("FAIL", "task.failed"),
    ("BLOCKED", "task.blocked"),
    ("NO_CHANGE", "task.completed"),
])
def test_maps_terminal_results_without_claiming_success(tmp_path: Path, status, expected):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-beta"}]})
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({"task_id": "task-beta", "status": status}) + "\n")
    output = tmp_path / "events.jsonl"

    build_event_ledger(queue, results, output, "run-456")
    events = [json.loads(line) for line in output.read_text().splitlines()]

    assert events[-1]["event_type"] == expected
    assert events[-1]["details"]["status"] == status


def test_unexecuted_task_is_assigned_but_not_marked_started_or_completed(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-waiting"}]})
    output = tmp_path / "events.jsonl"

    report = build_event_ledger(queue, tmp_path / "missing.jsonl", output, "run-789")
    events = [json.loads(line) for line in output.read_text().splitlines()]

    assert report["event_count"] == 1
    assert events[0]["event_type"] == "task.assigned"


def test_ignores_unmatched_diagnostic_rows_instead_of_guessing_task_identity(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-known"}]})
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({"message": "task-known passed"}) + "\n")
    output = tmp_path / "events.jsonl"

    report = build_event_ledger(queue, results, output, "run-identity")
    assert report["result_count"] == 0
    assert report["event_count"] == 1


def test_fails_closed_on_duplicate_queue_or_result_ids(tmp_path: Path):
    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-dup"}, {"id": "task-dup"}]})
    with pytest.raises(ValueError, match="duplicate queued"):
        build_event_ledger(queue, tmp_path / "missing.jsonl", tmp_path / "out.jsonl", "run-dup")

    queue = _write(tmp_path / "queue.json", {"tasks": [{"id": "task-dup"}]})
    results = tmp_path / "results.jsonl"
    row = json.dumps({"task_id": "task-dup", "status": "PASS"})
    results.write_text(row + "\n" + row + "\n")
    with pytest.raises(ValueError, match="duplicate result"):
        build_event_ledger(queue, results, tmp_path / "out.jsonl", "run-dup")


@pytest.mark.parametrize("run_id", ["", " " , None, "x" * 101])
def test_rejects_invalid_run_id(tmp_path: Path, run_id):
    queue = _write(tmp_path / "queue.json", {"tasks": []})
    with pytest.raises(ValueError, match="run ID"):
        build_event_ledger(queue, tmp_path / "missing.jsonl", tmp_path / "out.jsonl", run_id)
