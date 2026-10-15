from __future__ import annotations

import pytest

from scripts.replenish_autonomous_task_queue import build_queue


def test_rebuild_fills_queue_from_only_allowlisted_deterministic_targets():
    existing = {
        "version": 1,
        "max_tasks_per_run": 4,
        "tasks": [{
            "id": "known-task",
            "instruction": "Reviewed instruction",
            "allowed_paths": ["tests/test_known.py"],
        }],
    }
    targets = {
        "known-task": "tests/test_known.py",
        "new-known-task": "uhip/tests/test_contract.py",
    }

    rebuilt = build_queue(existing, targets)

    assert rebuilt["max_tasks_per_run"] == 4
    assert [task["id"] for task in rebuilt["tasks"]] == ["known-task", "new-known-task"]
    assert rebuilt["tasks"][0]["instruction"] == "Reviewed instruction"
    assert rebuilt["tasks"][1]["allowed_paths"] == ["uhip/tests/test_contract.py"]
    assert all(len(task["allowed_paths"]) == 1 for task in rebuilt["tasks"])


def test_rebuild_excludes_completed_ids_and_keeps_new_eligible_tasks():
    targets = {
        "already-done": "tests/test_done.py",
        "new-task": "tests/test_new.py",
    }

    rebuilt = build_queue({"tasks": []}, targets, completed_ids={"already-done"})

    assert [task["id"] for task in rebuilt["tasks"]] == ["new-task"]


def test_rebuild_returns_empty_queue_when_every_catalog_task_is_completed():
    targets = {
        "done-one": "tests/test_one.py",
        "done-two": "tests/test_two.py",
    }

    rebuilt = build_queue({"tasks": []}, targets, completed_ids={"done-one", "done-two"})

    assert rebuilt["tasks"] == []
    assert rebuilt["max_tasks_per_run"] == 4


@pytest.mark.parametrize("target", [
    "../secrets.env",
    "/tmp/unsafe.py",
    "scripts/deploy.py",
    "tests/../../secrets.env",
])
def test_rebuild_rejects_paths_outside_test_allowlist(target):
    with pytest.raises(ValueError):
        build_queue({"tasks": []}, {"unsafe-task": target})


def test_rebuild_rejects_duplicate_existing_ids():
    existing = {"tasks": [
        {"id": "same", "instruction": "one", "allowed_paths": ["tests/test_one.py"]},
        {"id": "same", "instruction": "two", "allowed_paths": ["tests/test_two.py"]},
    ]}
    with pytest.raises(ValueError, match="duplicate"):
        build_queue(existing, {"same": "tests/test_one.py"})


def test_rebuild_fails_closed_on_empty_catalog():
    with pytest.raises(ValueError, match="empty"):
        build_queue({"tasks": []}, {})


def test_rebuild_is_idempotent_after_new_task_is_completed():
    targets = {"first": "tests/test_first.py", "next": "tests/test_next.py"}
    first = build_queue({"tasks": []}, targets, completed_ids={"first"})
    assert [task["id"] for task in first["tasks"]] == ["next"]
    second = build_queue(first, targets, completed_ids={"first", "next"})
    assert second["tasks"] == []


def test_queue_empty_classifies_as_not_run_not_success():
    from scripts.run_minimal_autonomous_loop import classify_final_outcome

    outcome, reason = classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        recovery_outcome="success",
        queue_empty=True,
        requested_tasks=4,
        queue_completed=21,
        queue_total=21,
    )

    assert (outcome, reason) == ("NOT_RUN", "queue_empty")


def test_queue_empty_with_failed_postrun_gate_is_blocked():
    from scripts.run_minimal_autonomous_loop import classify_final_outcome

    outcome, reason = classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="failure",
        recovery_outcome="success",
        queue_empty=True,
        requested_tasks=4,
        queue_completed=21,
        queue_total=21,
    )

    assert outcome == "BLOCKED"
    assert "sheets" in reason
