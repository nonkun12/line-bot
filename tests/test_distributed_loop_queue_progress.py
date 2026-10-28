from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.distributed_loop_queue_progress import calculate_progress, main


def test_progress_does_not_count_not_run_result_as_completion(tmp_path: Path):
    queue = tmp_path / "runtime-queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": []}), encoding="utf-8")
    results.write_text(json.dumps({"task_id": "task-1", "status": "NOT_RUN", "failure_reason": "queue_empty"}) + "\n", encoding="utf-8")
    assert calculate_progress(queue, state, results) == {"queue_total": 1, "queue_completed": 0}


def test_progress_uses_runtime_queue_and_counts_refill_tasks(tmp_path: Path):
    queue = tmp_path / "runtime-queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": f"task-{i}"} for i in range(1, 26)]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": [f"task-{i}" for i in range(1, 23)]}), encoding="utf-8")
    results.write_text(json.dumps({"task_id": "task-23", "status": "PASS"}) + "\n", encoding="utf-8")

    assert calculate_progress(queue, state, results) == {"queue_total": 25, "queue_completed": 23}


def test_progress_does_not_double_count_run_task_already_in_state(tmp_path: Path):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": ["task-1"]}), encoding="utf-8")
    results.write_text(json.dumps({"task_id": "task-1", "status": "NO_CHANGE"}) + "\n", encoding="utf-8")

    assert calculate_progress(queue, state, results) == {"queue_total": 1, "queue_completed": 1}


def test_progress_rejects_duplicate_queue_ids(tmp_path: Path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}, {"id": "task-1"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        calculate_progress(queue, tmp_path / "missing-state.json", tmp_path / "missing-results.jsonl")


def test_progress_fails_closed_when_durable_state_is_missing(tmp_path: Path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing completed state"):
        calculate_progress(queue, tmp_path / "missing-state.json", tmp_path / "missing-results.jsonl")



@pytest.mark.parametrize("state_data", [{}, {"foo": 1}])
def test_progress_rejects_state_without_completed_key(tmp_path: Path, state_data: dict):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps(state_data), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid completed state"):
        calculate_progress(queue, state, results)



@pytest.mark.parametrize("broken_file", ["state", "results"])
def test_cli_returns_two_for_corrupt_evidence(tmp_path: Path, monkeypatch, capsys, broken_file: str):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": []}), encoding="utf-8")
    results.write_text("", encoding="utf-8")
    target = state if broken_file == "state" else results
    target.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["distributed_loop_queue_progress", "--queue", str(queue), "--state", str(state), "--results", str(results)],
    )

    assert main() == 2
    assert "QUEUE_PROGRESS_BLOCKED" in capsys.readouterr().out

@pytest.mark.parametrize("status", ["PASS", "NO_CHANGE"])
def test_progress_does_not_count_foreign_task_result_as_completion(tmp_path: Path, status: str):
    queue = tmp_path / "runtime-queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": []}), encoding="utf-8")
    results.write_text(
        json.dumps({"task_id": "foreign-task", "status": status}) + "\n",
        encoding="utf-8",
    )

    assert calculate_progress(queue, state, results) == {
        "queue_total": 1,
        "queue_completed": 0,
    }


def test_cli_fails_closed_and_reports_unexpected_exception(tmp_path: Path, monkeypatch, capsys):
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    results = tmp_path / "results.jsonl"
    queue.write_text(json.dumps({"tasks": [{"id": "task-1"}]}), encoding="utf-8")
    state.write_text(json.dumps({"completed": []}), encoding="utf-8")
    results.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["distributed_loop_queue_progress", "--queue", str(queue), "--state", str(state), "--results", str(results)],
    )

    def raise_unexpected(*args, **kwargs):
        raise RuntimeError("private details must not be printed")

    monkeypatch.setattr("scripts.distributed_loop_queue_progress.calculate_progress", raise_unexpected)
    assert main() == 2
    output = capsys.readouterr().out
    assert output.strip() == "QUEUE_PROGRESS_BLOCKED: RuntimeError"
    assert "private details" not in output
