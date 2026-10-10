from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import autonomous_loop_task_health as health
from scripts import run_minimal_autonomous_loop as loop

ROOT = Path(__file__).resolve().parents[1]


def _failed(state, task_id="task-one", reason="runtime_failed"):
    return health.record_task_result(state, task_id, "FAIL", reason)


def test_three_consecutive_failures_hold_task_and_store_reason():
    state = {"version": 1, "completed": []}
    assert _failed(state)["consecutive_failures"] == 1
    assert _failed(state)["consecutive_failures"] == 2
    final = _failed(state, reason="third_failure")
    assert final == {"consecutive_failures": 3, "held": True, "newly_held": True}
    assert health.held_task_ids(state) == {"task-one"}
    details, = health.held_details(state)
    assert details["reason"] == "third_failure"


@pytest.mark.parametrize("failure_count", [1, 2])
def test_resume_cannot_reset_a_task_before_hold_threshold(failure_count):
    state = {"version": 1, "completed": []}
    for _ in range(failure_count):
        _failed(state)
    before = json.dumps(state, sort_keys=True)
    with pytest.raises(ValueError, match="not on hold"):
        health.resume_task(state, "task-one")
    assert json.dumps(state, sort_keys=True) == before
    assert state["task_health"]["task-one"]["consecutive_failures"] == failure_count


def test_resume_is_allowed_only_after_hold_and_records_audit():
    state = {"version": 1, "completed": []}
    for _ in range(3):
        _failed(state)
    audit = health.resume_task(state, "task-one")
    assert audit["was_held"] is True
    assert audit["previous_consecutive_failures"] == 3
    assert "task_health" not in state
    assert state["resume_log"][-1]["task_id"] == "task-one"


@pytest.mark.parametrize("status", ["STOPPED", "NOT_RUN", "BLOCKED"])
def test_non_task_failures_do_not_increment_counter(status):
    state = {"version": 1, "completed": []}
    _failed(state)
    before = state["task_health"]["task-one"]["consecutive_failures"]
    health.record_task_result(state, "task-one", status, "operator_stop")
    assert state["task_health"]["task-one"]["consecutive_failures"] == before


def test_success_resets_prior_consecutive_failures():
    state = {"version": 1, "completed": []}
    _failed(state)
    _failed(state)
    health.record_task_result(state, "task-one", "PASS")
    assert "task_health" not in state


def test_corrupt_hold_data_fails_closed(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "version": 1, "completed": [],
        "task_health": {"task-one": {"consecutive_failures": 1, "held": True}},
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        health.read_state(path)


def _prepare_loop(monkeypatch, tmp_path: Path, task_ids, state=None):
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state or {"version": 1, "completed": []}), encoding="utf-8")
    results_path = tmp_path / "results.jsonl"
    stop_path = tmp_path / "stop"
    monkeypatch.setattr(loop, "QUEUE", queue_path)
    monkeypatch.setattr(loop, "load_tasks", lambda: [
        {"id": task_id, "instruction": "test-only", "allowed_paths": ["tests/test_dummy.py"]}
        for task_id in task_ids
    ])
    monkeypatch.delenv("AUTONOMOUS_LOOP_STOP", raising=False)
    monkeypatch.setattr(loop.sys, "argv", [
        "loop", "--max-tasks", "1", "--state", str(state_path),
        "--results", str(results_path), "--stop-file", str(stop_path),
    ])
    return state_path, results_path


def test_runner_skips_held_task_and_runs_healthy_task_behind_it(monkeypatch, tmp_path: Path):
    state = {"version": 1, "completed": [], "task_health": {
        "task-one": {
            "consecutive_failures": 3, "held": True,
            "held_at": "2026-10-10T00:00:00+00:00",
            "held_reason": "repeat_failure", "last_reason": "repeat_failure", "history": [],
        },
    }}
    state_path, results_path = _prepare_loop(monkeypatch, tmp_path, ["task-one", "task-two"], state)
    selected = []
    def fake_run(task, index, stop_file):
        selected.append(task["id"])
        return {"task_id": task["id"], "status": "PASS", "exit_code": 0, "failure_reason": ""}
    monkeypatch.setattr(loop, "run_task", fake_run)
    assert loop.main() == 0
    assert selected == ["task-two"]
    assert json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])["status"] == "PASS"
    assert health.held_task_ids(health.read_state(state_path)) == {"task-one"}


def test_runner_reports_blocked_when_every_pending_task_is_held(monkeypatch, tmp_path: Path):
    state = {"version": 1, "completed": [], "task_health": {
        "task-one": {
            "consecutive_failures": 3, "held": True, "held_reason": "repeat_failure",
            "last_reason": "repeat_failure", "history": [],
        },
    }}
    _, results_path = _prepare_loop(monkeypatch, tmp_path, ["task-one"], state)
    def unexpected_run(*_args):
        raise AssertionError("held task must not execute")
    monkeypatch.setattr(loop, "run_task", unexpected_run)
    assert loop.main() == 79
    result = json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])
    assert result["status"] == "BLOCKED"
    assert result["task_id"] == ""
    assert result["held_tasks"][0]["task_id"] == "task-one"


def test_failed_health_state_write_prevents_pass(monkeypatch, tmp_path: Path):
    state = {"version": 1, "completed": [], "task_health": {
        "task-one": {
            "consecutive_failures": 2, "held": False,
            "last_reason": "previous_failure", "history": [],
        },
    }}
    _, results_path = _prepare_loop(monkeypatch, tmp_path, ["task-one"], state)
    monkeypatch.setattr(
        loop, "run_task",
        lambda task, index, stop_file: {
            "task_id": task["id"], "status": "PASS", "exit_code": 0, "failure_reason": "",
        },
    )
    def fail_write(*_args, **_kwargs):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(loop.health, "write_state", fail_write)
    assert loop.main() == 1
    result = json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["failure_reason"] == "task_health_persist_failed"


def test_resume_cli_rejects_task_not_on_hold(monkeypatch, tmp_path: Path):
    state = {"version": 1, "completed": [], "task_health": {
        "task-one": {"consecutive_failures": 2, "held": False, "last_reason": "failure", "history": []},
    }}
    state_path, _ = _prepare_loop(monkeypatch, tmp_path, ["task-one"], state)
    monkeypatch.setattr(loop.sys, "argv", [
        "loop", "--max-tasks", "1", "--state", str(state_path),
        "--results", str(tmp_path / "results.jsonl"), "--stop-file", str(tmp_path / "stop"),
        "--resume-task", "task-one",
    ])
    with pytest.raises(SystemExit, match="cannot be resumed"):
        loop.main()
    assert json.loads(state_path.read_text(encoding="utf-8"))["task_health"]["task-one"]["consecutive_failures"] == 2


def test_workflow_requires_health_persistence_before_completed_state_and_publish():
    import yaml

    workflow = (ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)
    steps = parsed["jobs"]["minimal-loop"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    health_index = names.index("Persist task failure counters and holds")
    publish_index = names.index("Publish verified development branch")
    completed_index = names.index("Persist completed task state")
    assert health_index < publish_index < completed_index
    ledger = next(step for step in steps if step.get("name") == "Record distributed run result to Google Sheets")
    assert "TASK_HEALTH_OUTCOME" in ledger.get("env", {})
    assert "task_health_outcome != 'success'" in ledger["run"]
    assert "status = 'BLOCKED'" in ledger["run"]
    report = next(step for step in steps if step.get("name") == "Build final distributed loop report")
    assert "TASK_HEALTH_OUTCOME" in report.get("env", {})
    assert 'result_reason="task_health_persistence_' in report["run"]
    assert "resume_task_id" in workflow
