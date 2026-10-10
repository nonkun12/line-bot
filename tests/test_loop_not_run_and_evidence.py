"""Regression tests for NOT_RUN empty queues and consistent task evidence."""
import json
from pathlib import Path

import pytest

from scripts import run_minimal_autonomous_loop as loop


def _task(task_id="task-1"):
    return {"id": task_id, "instruction": "test", "allowed_paths": ["tests/test_loop_not_run_and_evidence.py"]}


def test_empty_queue_records_not_run_and_returns_78(monkeypatch, tmp_path, capsys):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": ["task-1"]}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [_task()])
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state), "--stop-file", str(tmp_path / "stop")])
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 78
    assert "NOT_RUN" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "NOT_RUN"
    assert row["failure_reason"] == "queue_empty"
    assert row["task_count"] == 0


def test_empty_task_list_records_not_run(monkeypatch, tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": []}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [])
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state), "--stop-file", str(tmp_path / "stop")])
    assert loop.main() == 78
    assert json.loads(results.read_text(encoding="utf-8").splitlines()[0])["status"] == "NOT_RUN"


def test_workflow_maps_only_exit_78_to_not_run():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'if [ "$loop_rc" -eq 78 ]' in workflow
    assert 'exit "$loop_rc"' in workflow
    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow
    assert ".autonomous-loop.stop" in workflow


def test_workflow_never_completes_zero_task_empty_queue():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'queue_exhausted_no_tasks' not in workflow
    assert '[ "$completed" -ge 1 ]' in workflow
    assert 'result="NOT_RUN"' in workflow


def test_workflow_state_is_not_advanced_for_empty_queue():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    persist = workflow[workflow.index("- name: Persist completed task state"):workflow.index("- name: Record distributed run result to Google Sheets")]
    assert "autonomous-loop-not-run" in persist
    assert "state unchanged" in persist
