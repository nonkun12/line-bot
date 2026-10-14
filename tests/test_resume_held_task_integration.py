"""Isolated integration coverage for the explicit held-task resume path.

Uses a temporary queue and a fake task runner; it never invokes a real model,
changes repository files, merges, or deploys.
"""
import json
from pathlib import Path

from scripts import run_minimal_autonomous_loop as loop
from scripts.recovery_ai import RecoveryStore


def test_resume_runs_one_fake_task_validates_evidence_and_persists_success(monkeypatch, tmp_path: Path):
    task = {
        "id": "resume-integration-task",
        "instruction": "Dummy bounded integration task",
        "allowed_paths": ["tests/test_resume_integration.py"],
    }
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"max_tasks_per_run": 1}), encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue_path)
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "stopped", lambda _path: False)

    state_path = tmp_path / "recovery-ai-state.json"
    store = RecoveryStore(state_path)
    for _ in range(3):
        decision = store.record_failure(task["id"], "timeout")
    assert decision.action == "HOLD"
    assert store.task_status(task["id"])["held"] is True

    executed = []

    def fake_run_task(selected_task, index, stop_file):
        executed.append(selected_task["id"])
        return {
            "timestamp": "2026-10-14T00:00:00+00:00",
            "run_index": index,
            "task_id": selected_task["id"],
            "status": "PASS",
            "exit_code": 0,
            "failure_reason": "",
            "base_sha": "a" * 40,
            "produced_sha": "a" * 40,
            "run_nonce": "b" * 32,
        }

    monkeypatch.setattr(loop, "run_task", fake_run_task)
    results_path = tmp_path / "results.jsonl"
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "run_minimal_autonomous_loop.py",
            "--max-tasks", "1",
            "--state", str(tmp_path / "loop-state.json"),
            "--results", str(results_path),
            "--resume-task-id", task["id"],
            "--confirm-cause-fixed",
        ],
    )

    assert loop.main() == 0
    assert executed == [task["id"]]

    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["task_id"] == task["id"]
    assert rows[0]["status"] == "PASS"
    assert rows[0]["recovery_ai"]["recorded"] is True
    assert rows[0]["recovery_ai"]["verified"] is True

    persisted = store.task_status(task["id"])
    assert persisted["held"] is False
    assert persisted["consecutive_failures"] == 0
    assert persisted["resume_count"] == 1
    assert persisted["resume_requires_review"] is True
    assert "last_success_at" in persisted
