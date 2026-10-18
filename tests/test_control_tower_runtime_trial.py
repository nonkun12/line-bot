"""Runtime-level Control Tower trial with the task executor fully mocked.

This exercises the real loop selection/preflight path while guaranteeing that no
subprocess, guarded runtime, queue mutation, merge, or deployment is invoked.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop


HEAD = "a" * 40
TASK = {
    "id": "trial-task",
    "instruction": "mocked one-task trial only",
    "allowed_paths": ["tests/test_control_tower_one_task_trial.py"],
}


def test_main_authorizes_one_task_then_calls_only_mock_executor(monkeypatch, tmp_path: Path):
    queue = tmp_path / "queue.json"
    queue.write_text('{"max_tasks_per_run": 1}', encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [dict(TASK)])
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "_git_head", lambda: HEAD)
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: [dict(TASK)])
    monkeypatch.setattr(loop, "stopped", lambda _path: False)
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "run_minimal_autonomous_loop.py",
            "--max-tasks", "1",
            "--state", str(tmp_path / "loop-state.json"),
            "--results", str(tmp_path / "results.jsonl"),
            "--stop-file", str(tmp_path / "stop"),
        ],
    )

    class FakeRecoveryStore:
        def __init__(self, _path):
            pass

        def task_status(self, _task_id):
            return {"held": False}

    import scripts.recovery_ai as recovery_ai
    monkeypatch.setattr(recovery_ai, "RecoveryStore", FakeRecoveryStore)

    adapter = types.ModuleType("scripts.control_tower_loop_adapter")
    adapter.authorize_registered_task = lambda task, catalog, head: (
        task["id"] == TASK["id"] and catalog[0]["id"] == TASK["id"] and head == HEAD,
        "ok",
    )
    recovery_adapter = types.ModuleType("scripts.recovery_ai_loop_adapter")
    recovery_adapter.record_loop_outcome = lambda _path, result: {
        "recorded": True,
        "status": result["status"],
    }
    observer = types.ModuleType("scripts.control_tower_loop_observer")
    observer.record_loop_observation = lambda _path, _result: {
        "recorded": True,
        "proposal_executable": False,
    }
    monkeypatch.setitem(sys.modules, "scripts.control_tower_loop_adapter", adapter)
    monkeypatch.setitem(sys.modules, "scripts.recovery_ai_loop_adapter", recovery_adapter)
    monkeypatch.setitem(sys.modules, "scripts.control_tower_loop_observer", observer)

    executor_calls = []

    def fake_run_task(task, index, stop_file, *, expected_base_sha=None):
        executor_calls.append((dict(task), index, expected_base_sha))
        return {
            "timestamp": "2026-10-18T00:00:00+00:00",
            "task_id": task["id"],
            "run_index": index,
            "status": "NO_CHANGE",
            "exit_code": 0,
            "base_sha": HEAD,
            "produced_sha": HEAD,
        }

    monkeypatch.setattr(loop, "run_task", fake_run_task)

    assert loop.main() == 0
    assert len(executor_calls) == 1
    assert executor_calls[0][0]["id"] == TASK["id"]
    assert executor_calls[0][1] == 1
    assert executor_calls[0][2] == HEAD

    records = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["status"] == "NO_CHANGE"
    assert records[0]["task_id"] == TASK["id"]
    assert records[0]["recovery_ai"]["recorded"] is True
    assert records[0]["control_tower"]["proposal_executable"] is False
