"""Focused regression tests for held-task blocking and explicit single-task resume."""
import json

import pytest

from scripts import run_minimal_autonomous_loop as loop
from scripts.recovery_ai import RecoveryStore


TASK_ID = "ai-speaker-empty-transcript-no-brain-call"
OTHER_TASK_ID = "loop-test-recovery-state-isolation"


def _task(task_id):
    return {
        "id": task_id,
        "instruction": "bounded regression test",
        "allowed_paths": ["tests/test_held_task_recovery_regressions.py"],
    }


def test_all_pending_tasks_held_returns_blocked_79_without_running(
    monkeypatch, tmp_path, capsys
):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": []}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    recovery_path = tmp_path / "recovery-ai-state.json"
    recovery_path.write_text(
        json.dumps({
            "schema_version": 1,
            "checkpoint": None,
            "tasks": {
                TASK_ID: {"held": True, "consecutive_failures": 1, "last_category": "unknown"}
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [_task(TASK_ID)])
    monkeypatch.setattr(
        loop.sys,
        "argv",
        [
            "loop", "--max-tasks", "1", "--results", str(results),
            "--state", str(state), "--stop-file", str(tmp_path / "stop"),
        ],
    )
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("held task must not run"))
    monkeypatch.setattr("scripts.recovery_ai.RecoveryStore", lambda path: RecoveryStore(recovery_path))

    assert loop.main() == 79
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "all_pending_tasks_held"
    assert row["task_count"] == 0
    assert "BLOCKED" in capsys.readouterr().out


def test_resume_requires_explicit_cause_fixed_and_only_unholds_target(tmp_path):
    store = RecoveryStore(tmp_path / "state.json")
    for task_id in (TASK_ID, OTHER_TASK_ID):
        store.record_failure(task_id, "unknown")

    with pytest.raises(ValueError, match="cause is fixed"):
        store.resume_held_task(TASK_ID, cause_fixed=False)

    store.resume_held_task(TASK_ID, cause_fixed=True)

    assert store.task_status(TASK_ID)["held"] is False
    assert store.task_status(TASK_ID)["consecutive_failures"] == 0
    assert store.task_status(TASK_ID)["resume_requires_review"] is True
    assert store.task_status(OTHER_TASK_ID)["held"] is True
