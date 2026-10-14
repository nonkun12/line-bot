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
            "--resume-actor", "test-operator",
            "--resume-run-id", "12345",
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
    assert rows[0]["resume_audit"]["operator"] == "test-operator"
    assert rows[0]["resume_audit"]["workflow_run_id"] == "12345"
    assert rows[0]["resume_audit"]["review_status"] == "audit_only_not_an_approval_gate"

    persisted = store.task_status(task["id"])
    assert persisted["held"] is False
    assert persisted["consecutive_failures"] == 0
    assert persisted["resume_count"] == 1
    assert persisted["resume_requires_review"] is True
    assert "last_success_at" in persisted



def test_resume_executes_selected_task_only_even_when_it_is_later_in_queue(monkeypatch, tmp_path: Path):
    first = {
        "id": "earlier-task",
        "instruction": "Must not run during resume",
        "allowed_paths": ["tests/test_earlier.py"],
    }
    target = {
        "id": "resume-target",
        "instruction": "Dummy resumed task",
        "allowed_paths": ["tests/test_target.py"],
    }
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"max_tasks_per_run": 2}), encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue_path)
    monkeypatch.setattr(loop, "load_tasks", lambda: [first, target])
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "stopped", lambda _path: False)

    state_path = tmp_path / "recovery-ai-state.json"
    store = RecoveryStore(state_path)
    for _ in range(3):
        store.record_failure(target["id"], "timeout")
    assert store.task_status(target["id"])["held"] is True

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
            "run_nonce": "c" * 32,
        }

    monkeypatch.setattr(loop, "run_task", fake_run_task)
    results_path = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop.sys, "argv", [
        "run_minimal_autonomous_loop.py",
        "--max-tasks", "2",
        "--state", str(tmp_path / "loop-state.json"),
        "--results", str(results_path),
        "--resume-task-id", target["id"],
        "--resume-actor", "test-operator",
        "--resume-run-id", "12346",
        "--confirm-cause-fixed",
    ])

    assert loop.main() == 0
    assert executed == [target["id"]]
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["task_id"] == target["id"]


def _prepare_interrupted_resume(monkeypatch, tmp_path: Path, *, budget: str, stop: bool):
    task = {
        "id": "resume-interrupted-before-start",
        "instruction": "Dummy bounded integration task",
        "allowed_paths": ["tests/test_resume_interrupted.py"],
    }
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"max_tasks_per_run": 1}), encoding="utf-8")
    monkeypatch.setattr(loop, "QUEUE", queue_path)
    monkeypatch.setattr(loop, "load_tasks", lambda: [task])
    monkeypatch.setattr(loop, "load_completed", lambda _path: set())
    monkeypatch.setattr(loop, "stopped", lambda _path: stop)
    monkeypatch.setenv("AUTONOMOUS_LOOP_BUDGET_SECONDS", budget)

    state_path = tmp_path / "recovery-ai-state.json"
    store = RecoveryStore(state_path)
    for _ in range(3):
        decision = store.record_failure(task["id"], "timeout")
    assert decision.action == "HOLD"

    results_path = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop.sys, "argv", [
        "run_minimal_autonomous_loop.py",
        "--max-tasks", "1",
        "--state", str(tmp_path / "loop-state.json"),
        "--results", str(results_path),
        "--resume-task-id", task["id"],
        "--resume-actor", "scheduled-auto-resume",
        "--resume-run-id", "12347",
        "--confirm-cause-fixed",
    ])
    return task, store, results_path


def test_resume_interrupted_by_budget_is_reheld_with_auditable_attempt(monkeypatch, tmp_path: Path):
    task, store, results_path = _prepare_interrupted_resume(
        monkeypatch, tmp_path, budget="100", stop=False
    )
    assert loop.main() == 80
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "BUDGET_EXHAUSTED"
    assert rows[0]["resume_audit"]["held_after_run"] is True
    assert rows[0]["resume_audit"]["interruption_reason"] == "loop_budget_insufficient_for_task"
    assert store.task_status(task["id"])["held"] is True
    assert store.task_status(task["id"])["resume_count"] == 1


def test_resume_interrupted_by_stop_switch_is_reheld_with_auditable_attempt(monkeypatch, tmp_path: Path):
    task, store, results_path = _prepare_interrupted_resume(
        monkeypatch, tmp_path, budget="0", stop=True
    )
    assert loop.main() == 1
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "STOPPED"
    assert rows[0]["resume_audit"]["held_after_run"] is True
    assert rows[0]["resume_audit"]["interruption_reason"] == "stop_requested_before_task"
    assert store.task_status(task["id"])["held"] is True
    assert store.task_status(task["id"])["resume_count"] == 1
