import json

import pytest

from scripts.recovery_ai import RecoveryStore
from scripts.resume_held_task import resume_task


TASK_ID = "ai-speaker-empty-transcript-no-brain-call"
OTHER_TASK_ID = "loop-test-recovery-state-isolation"


def _held_state(path, task_id):
    store = RecoveryStore(path)
    store.record_failure(task_id, "unknown")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixtures(tmp_path):
    recovery_path = tmp_path / "recovery-ai-state.json"
    _held_state(recovery_path, TASK_ID)
    _held_state(recovery_path, OTHER_TASK_ID)
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    state_path = tmp_path / "state.json"
    _write(state_path, {"version": 1, "completed": [], "recovery_ai": recovery})
    queue_path = tmp_path / "queue.json"
    _write(queue_path, {"tasks": [
        {"id": TASK_ID, "instruction": "bounded task", "allowed_paths": ["tests/"]},
        {"id": OTHER_TASK_ID, "instruction": "bounded task", "allowed_paths": ["tests/"]},
    ]})
    return state_path, recovery_path, queue_path


def test_resume_requires_explicit_cause_fixed_confirmation(tmp_path):
    state, recovery, queue = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="cause is fixed"):
        resume_task(
            state_path=state,
            recovery_path=recovery,
            queue_path=queue,
            task_id=TASK_ID,
            cause_fixed=False,
        )
    assert RecoveryStore(recovery).task_status(TASK_ID)["held"] is True


def test_resume_unholds_only_requested_pending_task_and_persists_state(tmp_path):
    state, recovery, queue = _fixtures(tmp_path)
    result = resume_task(
        state_path=state,
        recovery_path=recovery,
        queue_path=queue,
        task_id=TASK_ID,
        cause_fixed=True,
    )
    assert result == {
        "task_id": TASK_ID,
        "held": False,
        "resume_requires_review": True,
    }
    assert RecoveryStore(recovery).task_status(TASK_ID)["held"] is False
    assert RecoveryStore(recovery).task_status(TASK_ID)["resume_requires_review"] is True
    assert RecoveryStore(recovery).task_status(OTHER_TASK_ID)["held"] is True
    assert json.loads(state.read_text(encoding="utf-8"))["recovery_ai"] == json.loads(
        recovery.read_text(encoding="utf-8")
    )


def test_resume_rejects_completed_or_unknown_task(tmp_path):
    state, recovery, queue = _fixtures(tmp_path)
    data = json.loads(state.read_text(encoding="utf-8"))
    data["completed"] = [TASK_ID]
    _write(state, data)
    with pytest.raises(ValueError, match="completed tasks"):
        resume_task(
            state_path=state, recovery_path=recovery, queue_path=queue,
            task_id=TASK_ID, cause_fixed=True,
        )
    with pytest.raises(ValueError, match="exactly one queued task"):
        resume_task(
            state_path=state, recovery_path=recovery, queue_path=queue,
            task_id="unknown-task", cause_fixed=True,
        )



def test_resume_accepts_catalog_only_task_when_tracked_queue_is_exhausted(tmp_path):
    state, recovery, _tracked_queue = _fixtures(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    _write(catalog_path, {"tasks": [
        {"id": TASK_ID, "instruction": "reviewed catalog task", "allowed_paths": ["tests/test_example.py"]},
    ]})

    result = resume_task(
        state_path=state,
        recovery_path=recovery,
        queue_path=catalog_path,
        task_id=TASK_ID,
        cause_fixed=True,
    )

    assert result["task_id"] == TASK_ID
    assert result["resume_requires_review"] is True
    assert RecoveryStore(recovery).task_status(TASK_ID)["held"] is False
    assert RecoveryStore(recovery).task_status(TASK_ID)["resume_requires_review"] is True
    assert RecoveryStore(recovery).task_status(OTHER_TASK_ID)["held"] is True
