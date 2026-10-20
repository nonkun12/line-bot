import json

import pytest

from scripts.confirm_recovery_resume_review import confirm_in_durable_state
from scripts.recovery_ai import RecoveryStore, RecoveryStateError


def _state_with_pending_review(path):
    recovery_path = path.parent / "recovery-source.json"
    store = RecoveryStore(recovery_path)
    for _ in range(3):
        store.record_failure("task-a", "timeout")
    store.resume_held_task("task-a", cause_fixed=True)
    state = {
        "version": 1,
        "completed": [],
        "recovery_ai": json.loads(recovery_path.read_text(encoding="utf-8")),
        "recovery_rag": [],
    }
    path.write_text(json.dumps(state), encoding="utf-8")


def test_confirm_review_updates_durable_state_and_preserves_other_fields(tmp_path):
    state_path = tmp_path / ".autonomous-loop-state.json"
    _state_with_pending_review(state_path)
    confirm_in_durable_state(state_path, "task-a")

    durable = json.loads(state_path.read_text(encoding="utf-8"))
    record = durable["recovery_ai"]["tasks"]["task-a"]
    assert record["held"] is False
    assert record["resume_requires_review"] is False
    assert record["resume_reviewed_at"]
    assert durable["completed"] == []
    assert durable["recovery_rag"] == []


def test_confirm_review_rejects_unknown_task_without_mutating_state(tmp_path):
    state_path = tmp_path / ".autonomous-loop-state.json"
    _state_with_pending_review(state_path)
    before = state_path.read_bytes()

    with pytest.raises(ValueError, match="explicitly resumed"):
        confirm_in_durable_state(state_path, "missing-task")

    assert state_path.read_bytes() == before


def test_confirm_review_rejects_corrupt_durable_state(tmp_path):
    state_path = tmp_path / ".autonomous-loop-state.json"
    state_path.write_text("{broken", encoding="utf-8")
    before = state_path.read_bytes()

    with pytest.raises(RecoveryStateError, match="unreadable"):
        confirm_in_durable_state(state_path, "task-a")

    assert state_path.read_bytes() == before
