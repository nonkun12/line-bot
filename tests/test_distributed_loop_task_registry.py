"""Regression tests for deterministic distributed-loop task registration."""
import json

from core import line_development_runtime as runtime


TASK_ID = "router-regression-general-request-metadata"
TARGET = "tests/test_management_router.py"
ANCHOR = "def test_unresolved_request_records_empty_candidates() -> None:"
TEST_NAME = "test_router_regression_general_request_keeps_channel_and_request_metadata"


def test_new_queue_task_has_one_exact_allowed_target() -> None:
    assert runtime._DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[TASK_ID] == TARGET


def test_new_queue_task_plan_is_bounded_valid_and_idempotent(monkeypatch, tmp_path) -> None:
    target_path = tmp_path / TARGET
    target_path.parent.mkdir(parents=True)
    original = f"{ANCHOR}\n    pass\n"
    target_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, error = runtime._deterministic_autonomous_test_plan(TARGET, task_id=TASK_ID)

    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert change["file"] == TARGET
    assert change["old"] == f"{ANCHOR}\n"
    assert TEST_NAME in change["new"]
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, TARGET, "exec")

    target_path.write_text(candidate, encoding="utf-8")
    repeated, repeated_error = runtime._deterministic_autonomous_test_plan(TARGET, task_id=TASK_ID)
    assert repeated_error is None
    assert repeated == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_new_queue_task_rejects_an_unapproved_target() -> None:
    plan, error = runtime._deterministic_autonomous_test_plan(
        "tests/test_unrelated.py", task_id=TASK_ID
    )
    assert plan is None
    assert error == "deterministic_target_mismatch"


def test_recovery_readback_task_plan_is_bounded_and_idempotent(monkeypatch, tmp_path) -> None:
    task_id = "recovery-ai-loop-adapter-durable-state-readback"
    target = "tests/test_recovery_ai_loop_adapter.py"
    target_path = tmp_path / target
    target_path.parent.mkdir(parents=True)
    anchor = "def test_invalid_evidence_holds_for_human_review(tmp_path):\n"
    original = anchor + "    pass\n"
    target_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, error = runtime._deterministic_autonomous_test_plan(target, task_id=task_id)

    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert change["file"] == target
    assert change["old"] == anchor
    assert "test_failure_record_survives_new_store_readback" in change["new"]
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, target, "exec")

    target_path.write_text(candidate, encoding="utf-8")
    repeated, repeated_error = runtime._deterministic_autonomous_test_plan(target, task_id=task_id)
    assert repeated_error is None
    assert repeated == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_recovery_state_isolation_task_plan_is_bounded_and_idempotent(monkeypatch, tmp_path) -> None:
    task_id = "loop-test-recovery-state-isolation"
    target = "tests/test_minimal_autonomous_loop.py"
    target_path = tmp_path / target
    target_path.parent.mkdir(parents=True)
    anchor = '    assert json.loads(lines[0])["task_id"] == "t1"\n'
    original = anchor
    target_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(runtime.worker, "ROOT", tmp_path)

    plan, error = runtime._deterministic_autonomous_test_plan(target, task_id=task_id)

    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is False
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert change["file"] == target
    assert change["old"] == anchor
    assert "test_main_halts_after_first_failure_persists_recovery_state" in change["new"]
    candidate = original.replace(change["old"], change["new"], 1)
    compile(candidate, target, "exec")

    target_path.write_text(candidate, encoding="utf-8")
    repeated, repeated_error = runtime._deterministic_autonomous_test_plan(target, task_id=task_id)
    assert repeated_error is None
    assert repeated == {"no_change": True, "source": "deterministic_autonomous_task"}


def test_queue_ids_are_unique_and_all_targets_match_the_registry() -> None:
    root = runtime.worker.ROOT
    queue = json.loads((root / ".github" / "autonomous-loop-tasks.json").read_text(encoding="utf-8"))
    tasks = queue["tasks"]
    ids = [item["id"] for item in tasks]

    assert 1 <= queue["max_tasks_per_run"] <= 4
    assert len(ids) == len(set(ids))
    for item in tasks:
        allowed_paths = item["allowed_paths"]
        assert len(allowed_paths) == 1
        assert runtime._DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[item["id"]] == allowed_paths[0]
