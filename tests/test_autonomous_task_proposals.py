from __future__ import annotations
import json
from pathlib import Path
import pytest
from scripts.autonomous_task_proposals import build_proposals, SPEC_MARKER


def write(path: Path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def state(completed=None, tasks=None):
    return {"completed": completed or [], "recovery_ai": {"schema_version": 1, "tasks": tasks or {}, "checkpoint": None}}


def issue(task_id="fresh-task", labels=("autonomous-task-candidate",), path="tests/test_example.py",
          instruction="Add a focused regression test."):
    spec = {"id": task_id, "instruction": instruction, "allowed_paths": [path]}
    return {"number": 17, "state": "open", "labels": [{"name": x} for x in labels],
            "body": f"{SPEC_MARKER}\n{json.dumps(spec)}\n{SPEC_MARKER}"}


def registered(task_id, instruction="Add a focused regression test.", path="tests/test_example.py"):
    return {"id": task_id, "instruction": instruction, "allowed_paths": [path]}


def run(tmp_path, issues, durable, registered_tasks=(), queue_data=None):
    ip = write(tmp_path / "issues.json", issues)
    qp = write(tmp_path / "queue.json", queue_data or {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", durable)
    cp = write(tmp_path / "catalog.json", {"version": 1, "tasks": list(registered_tasks)})
    result = build_proposals(ip, qp, sp, tmp_path / "proposals.json", cp)
    return result, qp


def test_generates_review_only_proposal(tmp_path):
    result, _ = run(tmp_path, [issue()], state())
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["proposal_count"] == 1
    assert result["proposals"][0]["status"] == "REVIEW_REQUIRED"
    assert result["proposals"][0]["source_issue"] == 17


def test_skips_completed_held_and_unlabeled_issues(tmp_path):
    result, _ = run(tmp_path, [issue("done"), issue("held"), issue("untrusted", labels=())],
                    state(completed=["done"], tasks={"held": {"held": True}}))
    assert result["proposal_count"] == 0
    assert result["reason"] == "no_open_labeled_issue_with_valid_test_only_spec"


@pytest.mark.parametrize("path", ["../secret.env", "app.py", "tests/test_*.py"])
def test_rejects_non_allowlisted_paths(tmp_path, path):
    result, _ = run(tmp_path, [issue(path=path)], state())
    assert result["proposal_count"] == 0


def test_fails_closed_on_missing_recovery_state(tmp_path):
    with pytest.raises(ValueError, match="Recovery AI state"):
        run(tmp_path, [issue()], {"completed": []})


def test_fails_closed_when_true_recovery_flag_masks_malformed_sibling(tmp_path):
    with pytest.raises(ValueError, match="Recovery AI task flags"):
        run(tmp_path, [issue("new-task", labels=("autonomous-task-approved",))],
            state(tasks={"held-task": {"held": True, "resume_requires_review": "invalid"}}))


def test_explicitly_approved_registered_test_only_issue_enters_bounded_runtime_queue(tmp_path):
    result, qp = run(tmp_path, [issue("approved-task", labels=("autonomous-task-approved",))],
                     state(), registered_tasks=[registered("approved-task")])
    queue_after = json.loads(qp.read_text(encoding="utf-8"))
    assert result["status"] == "QUEUED_APPROVED"
    assert result["approved_task_ids"] == ["approved-task"]
    assert result["proposal_count"] == 0
    assert [task["id"] for task in queue_after["tasks"]] == ["approved-task"]
    assert queue_after["tasks"][0]["allowed_paths"] == ["tests/test_example.py"]


def test_candidate_only_issue_never_enters_executable_queue(tmp_path):
    result, qp = run(tmp_path, [issue("candidate-task")], state(),
                     registered_tasks=[registered("candidate-task")])
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["proposal_count"] == 1
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []


def test_approved_but_unregistered_issue_is_rejected_before_dispatch(tmp_path):
    result, qp = run(tmp_path, [issue("not-registered", labels=("autonomous-task-approved",))], state())
    assert result["status"] == "APPROVED_TASKS_REJECTED_UNREGISTERED"
    assert result["rejected_approved_count"] == 1
    assert result["rejected_approved_tasks"] == [{
        "id": "not-registered", "source_issue": 17,
        "reason": "not_in_registered_catalog_or_spec_mismatch",
    }]
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []


def test_approved_issue_spec_must_exactly_match_registered_definition(tmp_path):
    result, qp = run(tmp_path, [issue("registered-task", labels=("autonomous-task-approved",))], state(),
                     registered_tasks=[registered("registered-task", instruction="Different instruction.")])
    assert result["approved_count"] == 0
    assert result["rejected_approved_count"] == 1
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []


def test_approved_tasks_respect_remaining_queue_capacity(tmp_path):
    existing = {"id": "already-queued", "instruction": "Existing task", "allowed_paths": ["tests/test_existing.py"]}
    issues = [issue("approved-one", labels=("autonomous-task-approved",)),
              issue("approved-two", labels=("autonomous-task-approved",))]
    result, qp = run(tmp_path, issues, state(), registered_tasks=[
        registered("approved-one"), registered("approved-two")
    ], queue_data={"version": 1, "max_tasks_per_run": 1, "tasks": [existing]})
    assert result["approved_count"] == 0
    assert [task["id"] for task in json.loads(qp.read_text(encoding="utf-8"))["tasks"]] == ["already-queued"]


def test_approved_task_is_not_requeued_when_completed_or_held(tmp_path):
    issues = [issue("already-done", labels=("autonomous-task-approved",)),
              issue("held-task", labels=("autonomous-task-approved",))]
    result, qp = run(tmp_path, issues, state(completed=["already-done"], tasks={"held-task": {"held": True}}),
                     registered_tasks=[registered("already-done"), registered("held-task")])
    assert result["approved_count"] == 0
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []


@pytest.mark.parametrize("limit", [True, False])
def test_build_proposals_rejects_boolean_runtime_task_limit(tmp_path, limit):
    issues_path = write(tmp_path / "issues.json", [issue()])
    queue_path = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": limit, "tasks": []})
    state_path = write(tmp_path / "state.json", state())
    catalog_path = write(tmp_path / "catalog.json", {"version": 1, "tasks": []})
    with pytest.raises(ValueError, match="invalid runtime task limit"):
        build_proposals(issues_path, queue_path, state_path, tmp_path / "proposals.json", catalog_path)


def test_build_proposals_rejects_boolean_max_tasks_per_run(tmp_path):
    issues_path = write(tmp_path / "issues.json", [issue()])
    queue_path = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": True, "tasks": []})
    state_path = write(tmp_path / "state.json", state())
    catalog_path = write(tmp_path / "catalog.json", {"version": 1, "tasks": []})
    with pytest.raises(ValueError, match="invalid runtime task limit"):
        build_proposals(issues_path, queue_path, state_path, tmp_path / "proposals.json", catalog_path)
