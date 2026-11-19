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


def test_confirm_review_updates_local_recovery_state_with_durable_state(tmp_path):
    state_path = tmp_path / ".autonomous-loop-state.json"
    _state_with_pending_review(state_path)
    recovery_path = tmp_path / "recovery-ai-state.json"
    recovery_path.write_text(
        json.dumps(json.loads(state_path.read_text(encoding="utf-8"))["recovery_ai"]),
        encoding="utf-8",
    )

    confirm_in_durable_state(state_path, "task-a", recovery_path)

    durable = json.loads(state_path.read_text(encoding="utf-8"))["recovery_ai"]
    local = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert local == durable
    assert local["tasks"]["task-a"]["resume_requires_review"] is False


def test_confirm_review_rejects_mismatched_local_recovery_state(tmp_path):
    state_path = tmp_path / ".autonomous-loop-state.json"
    _state_with_pending_review(state_path)
    recovery_path = tmp_path / "recovery-ai-state.json"
    recovery_path.write_text(json.dumps({"schema_version": 1, "tasks": {}, "checkpoint": {}}))

    before = state_path.read_bytes()
    with pytest.raises(RecoveryStateError, match="state mismatch"):
        confirm_in_durable_state(state_path, "task-a", recovery_path)

    assert state_path.read_bytes() == before


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


def test_main_blocks_corrupt_durable_state_without_mutating_file(
    tmp_path, monkeypatch, capsys
):
    state_path = tmp_path / ".autonomous-loop-state.json"
    state_path.write_text("{broken", encoding="utf-8")
    before = state_path.read_bytes()

    module_globals = confirm_in_durable_state.__globals__
    namespace = module_globals["argparse"].Namespace(
        state_file=str(state_path),
        task_id="task-a",
        recovery_state_file=None,
    )
    monkeypatch.setattr(
        module_globals["argparse"].ArgumentParser,
        "parse_args",
        lambda _self: namespace,
    )

    result = module_globals["main"]()
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out.strip() == "Recovery AI resume review blocked: RecoveryStateError"
    assert state_path.read_bytes() == before


def test_main_blocks_unknown_task_with_value_error_without_mutating_file(
    tmp_path, monkeypatch, capsys
):
    state_path = tmp_path / ".autonomous-loop-state.json"
    _state_with_pending_review(state_path)
    before = state_path.read_bytes()

    module_globals = confirm_in_durable_state.__globals__
    namespace = module_globals["argparse"].Namespace(
        state_file=str(state_path),
        task_id="missing-task",
        recovery_state_file=None,
    )
    monkeypatch.setattr(
        module_globals["argparse"].ArgumentParser,
        "parse_args",
        lambda _self: namespace,
    )

    result = module_globals["main"]()
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out.strip() == "Recovery AI resume review blocked: ValueError"
    assert state_path.read_bytes() == before

def test_main_passes_cli_paths_and_task_id_to_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    import sys

    from scripts import confirm_recovery_resume_review

    state_file = tmp_path / "durable-state.json"
    task_id = "task-cli-review"
    called = {}

    def capture_confirmation(state_path, received_task_id, recovery_state_path=None):
        called["state_path"] = state_path
        called["task_id"] = received_task_id
        called["recovery_state_path"] = recovery_state_path

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "confirm_recovery_resume_review",
            "--state-file", str(state_file),
            "--task-id", task_id,
        ],
    )
    monkeypatch.setattr(
        confirm_recovery_resume_review,
        "confirm_in_durable_state",
        capture_confirmation,
    )

    assert confirm_recovery_resume_review.main() == 0
    assert called["state_path"] == str(state_file)
    assert called["task_id"] == task_id
