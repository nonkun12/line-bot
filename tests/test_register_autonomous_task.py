from __future__ import annotations

import json

import pytest

from scripts.register_autonomous_task import SPEC_MARKER, register_candidate


def issue(task_id="new-test-task", labels=("autonomous-task-candidate",), path="tests/test_example.py"):
    spec = {
        "id": task_id,
        "instruction": "テスト専用: tests/test_example.py に回帰テストを1件追加してください。",
        "allowed_paths": [path],
    }
    return {
        "number": 1091,
        "state": "open",
        "labels": [{"name": name} for name in labels],
        "body": f"{SPEC_MARKER}\n{json.dumps(spec, ensure_ascii=False)}\n{SPEC_MARKER}",
    }


def catalog(tasks=None):
    return {"version": 1, "max_additions_per_run": 4, "tasks": tasks or []}


def state(tasks=None, completed=None):
    return {
        "completed": completed or [],
        "recovery_ai": {"schema_version": 1, "tasks": tasks or {}, "checkpoint": None},
    }


def queue(tasks=None):
    return {"version": 1, "max_tasks_per_run": 4, "tasks": tasks or []}


def register(candidate=None, registered=None, durable=None, runtime=None, confirmation="1091"):
    return register_candidate(
        candidate or issue(),
        registered or catalog(),
        durable or state(),
        runtime or queue(),
        confirmation,
    )


def test_registers_reviewed_candidate_without_approving_or_queueing_it():
    updated = register()
    assert updated["tasks"] == [{
        "id": "new-test-task",
        "instruction": "テスト専用: tests/test_example.py に回帰テストを1件追加してください。",
        "allowed_paths": ["tests/test_example.py"],
    }]


def test_requires_exact_issue_number_confirmation():
    with pytest.raises(ValueError, match="confirmation"):
        register(confirmation="1092")


@pytest.mark.parametrize("labels", [
    ("autonomous-task-candidate", "autonomous-task-approved"),
    ("autonomous-task-approved",),
    (),
])
def test_requires_candidate_only_label(labels):
    with pytest.raises(ValueError, match="candidate-only"):
        register(candidate=issue(labels=labels))


def test_rejects_non_test_paths():
    with pytest.raises(ValueError, match="allowlisted test file"):
        register(candidate=issue(path="core/control_tower.py"))


def test_rejects_duplicate_catalog_task_id():
    existing = {"id": "new-test-task", "instruction": "old", "allowed_paths": ["tests/test_old.py"]}
    with pytest.raises(ValueError, match="already registered"):
        register(registered=catalog([existing]))


def test_rejects_completed_or_queued_task_ids():
    with pytest.raises(ValueError, match="already completed"):
        register(durable=state(completed=["new-test-task"]))
    with pytest.raises(ValueError, match="already queued"):
        register(runtime=queue([{"id": "new-test-task"}]))


def test_rejects_existing_recovery_state_even_when_not_held():
    with pytest.raises(ValueError, match="Recovery AI state"):
        register(durable=state(tasks={"new-test-task": {"held": False, "resume_requires_review": False}}))


def test_fails_closed_on_malformed_durable_state():
    with pytest.raises(ValueError, match="Recovery AI state"):
        register(durable={"completed": [], "recovery_ai": {"schema_version": 1, "tasks": []}})
