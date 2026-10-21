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
