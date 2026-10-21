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

def issue(task_id="fresh-task", labels=("autonomous-task-candidate",), path="tests/test_example.py"):
    spec = {"id": task_id, "instruction": "Add a focused regression test.", "allowed_paths": [path]}
    return {"number": 17, "state": "open", "labels": [{"name": x} for x in labels],
            "body": f"{SPEC_MARKER}\n{json.dumps(spec)}\n{SPEC_MARKER}"}

def run(tmp_path, issues, durable):
    ip = write(tmp_path / "issues.json", issues)
    qp = write(tmp_path / "queue.json", {"tasks": []})
    sp = write(tmp_path / "state.json", durable)
    return build_proposals(ip, qp, sp, tmp_path / "proposals.json")

def test_generates_review_only_proposal(tmp_path):
    result = run(tmp_path, [issue()], state())
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["proposal_count"] == 1
    assert result["proposals"][0]["status"] == "REVIEW_REQUIRED"
    assert result["proposals"][0]["source_issue"] == 17

def test_skips_completed_held_and_unlabeled_issues(tmp_path):
    result = run(tmp_path, [issue("done"), issue("held"), issue("untrusted", labels=())],
                 state(completed=["done"], tasks={"held": {"held": True}}))
    assert result["proposal_count"] == 0
    assert result["reason"] == "no_open_labeled_issue_with_valid_test_only_spec"

@pytest.mark.parametrize("path", ["../secret.env", "app.py", "tests/test_*.py"])
def test_rejects_non_allowlisted_paths(tmp_path, path):
    assert run(tmp_path, [issue(path=path)], state())["proposal_count"] == 0

def test_fails_closed_on_missing_recovery_state(tmp_path):
    with pytest.raises(ValueError, match="Recovery AI state"):
        run(tmp_path, [issue()], {"completed": []})


def test_fails_closed_when_true_recovery_flag_masks_malformed_sibling(tmp_path):
    with pytest.raises(ValueError, match="Recovery AI task flags"):
        run(
            tmp_path,
            [issue("new-task", labels=("autonomous-task-approved",))],
            state(tasks={"held-task": {"held": True, "resume_requires_review": "invalid"}}),
        )


def test_explicitly_approved_test_only_issue_enters_bounded_runtime_queue(tmp_path):
    issues = [issue("approved-task", labels=("autonomous-task-approved",))]
    ip = write(tmp_path / "issues.json", issues)
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", state())
    result = build_proposals(ip, qp, sp, tmp_path / "proposals.json")

    queue_after = json.loads(qp.read_text(encoding="utf-8"))
    assert result["status"] == "QUEUED_APPROVED"
    assert result["approved_task_ids"] == ["approved-task"]
    assert result["proposal_count"] == 0
    assert [task["id"] for task in queue_after["tasks"]] == ["approved-task"]
    assert queue_after["tasks"][0]["allowed_paths"] == ["tests/test_example.py"]


def test_candidate_only_issue_never_enters_executable_queue(tmp_path):
    ip = write(tmp_path / "issues.json", [issue("candidate-task")])
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", state())
    result = build_proposals(ip, qp, sp, tmp_path / "proposals.json")

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["proposal_count"] == 1
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []


def test_approved_tasks_respect_remaining_queue_capacity(tmp_path):
    existing = {"id": "already-queued", "instruction": "Existing task", "allowed_paths": ["tests/test_existing.py"]}
    issues = [issue("approved-one", labels=("autonomous-task-approved",)),
              issue("approved-two", labels=("autonomous-task-approved",))]
    ip = write(tmp_path / "issues.json", issues)
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 1, "tasks": [existing]})
    sp = write(tmp_path / "state.json", state())
    result = build_proposals(ip, qp, sp, tmp_path / "proposals.json")

    queue_after = json.loads(qp.read_text(encoding="utf-8"))
    assert result["approved_count"] == 0
    assert [task["id"] for task in queue_after["tasks"]] == ["already-queued"]


def test_approved_task_is_not_requeued_when_completed_or_held(tmp_path):
    issues = [issue("already-done", labels=("autonomous-task-approved",)),
              issue("held-task", labels=("autonomous-task-approved",))]
    ip = write(tmp_path / "issues.json", issues)
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", state(
        completed=["already-done"],
        tasks={"held-task": {"held": True}},
    ))
    result = build_proposals(ip, qp, sp, tmp_path / "proposals.json")

    assert result["approved_count"] == 0
    assert json.loads(qp.read_text(encoding="utf-8"))["tasks"] == []



def test_auto_refill_queues_one_test_only_task_when_queue_is_empty(tmp_path):
    from hashlib import sha256

    target = tmp_path / "tests" / "test_autonomous_task_proposals.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_existing_behavior():\\n    assert True\\n", encoding="utf-8")
    ip = write(tmp_path / "issues.json", [issue("review-only")])
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", state())

    result = build_proposals(
        ip, qp, sp, tmp_path / "proposals.json",
        enable_auto_refill=True, repo_root=tmp_path,
    )

    queued = json.loads(qp.read_text(encoding="utf-8"))["tasks"]
    expected_fingerprint = sha256(target.read_bytes()).hexdigest()[:12]
    assert result["status"] == "AUTO_QUEUED_AND_REVIEW_REQUIRED"
    assert result["auto_queued_count"] == 1
    assert result["proposal_count"] == 1
    assert len(queued) == 1
    assert queued[0]["id"].endswith(expected_fingerprint)
    assert queued[0]["allowed_paths"] == ["tests/test_autonomous_task_proposals.py"]
    assert "NO_CHANGE" in queued[0]["instruction"]


def test_auto_refill_skips_completed_fingerprint_and_selects_next_fixed_target(tmp_path):
    first = tmp_path / "tests" / "test_autonomous_task_proposals.py"
    second = tmp_path / "tests" / "test_autonomous_task_refill.py"
    first.parent.mkdir(parents=True)
    first.write_text("first target\\n", encoding="utf-8")
    second.write_text("second target\\n", encoding="utf-8")
    first_id = (
        "auto-test-test-autonomous-task-proposals-"
        + __import__("hashlib").sha256(first.read_bytes()).hexdigest()[:12]
    )
    ip = write(tmp_path / "issues.json", [])
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": []})
    sp = write(tmp_path / "state.json", state(completed=[first_id]))

    result = build_proposals(
        ip, qp, sp, tmp_path / "proposals.json",
        enable_auto_refill=True, repo_root=tmp_path,
    )

    queued = json.loads(qp.read_text(encoding="utf-8"))["tasks"]
    assert result["auto_queued_count"] == 1
    assert len(queued) == 1
    assert queued[0]["allowed_paths"] == ["tests/test_autonomous_task_refill.py"]
    assert queued[0]["id"].endswith(__import__("hashlib").sha256(second.read_bytes()).hexdigest()[:12])


def test_auto_refill_never_appends_when_curated_queue_is_not_empty(tmp_path):
    target = tmp_path / "tests" / "test_autonomous_task_proposals.py"
    target.parent.mkdir(parents=True)
    target.write_text("target\\n", encoding="utf-8")
    existing = {"id": "curated-task", "instruction": "Do the curated task.", "allowed_paths": ["tests/test_autonomous_task_proposals.py"]}
    ip = write(tmp_path / "issues.json", [])
    qp = write(tmp_path / "queue.json", {"version": 1, "max_tasks_per_run": 4, "tasks": [existing]})
    sp = write(tmp_path / "state.json", state())

    result = build_proposals(
        ip, qp, sp, tmp_path / "proposals.json",
        enable_auto_refill=True, repo_root=tmp_path,
    )

    queued = json.loads(qp.read_text(encoding="utf-8"))["tasks"]
    assert result["auto_queued_count"] == 0
    assert [task["id"] for task in queued] == ["curated-task"]
