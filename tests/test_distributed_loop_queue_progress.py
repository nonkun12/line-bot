from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.distributed_loop_queue_progress import calculate_progress


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
