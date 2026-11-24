import json
import subprocess
import pytest
from scripts.publish_autonomous_task_issue_drafts import _validate, publish

def draft():
    task_id = "review-coverage-gap-0123456789"
    body = ("実行承認ではありません。\nQueue admission: not authorized\n"
            "<!-- autonomous-task-spec -->\n" +
            json.dumps({"id": task_id, "allowed_paths": ["tests/test_agent_runtime.py"]}) +
            "\n<!-- autonomous-task-spec -->")
    return {"task_id": task_id, "title": "Review-only test task", "body": body}

def test_rejects_execution_authority():
    row = draft()
    row["body"] = row["body"].replace('"allowed_paths": ["tests/test_agent_runtime.py"]',
        '"allowed_paths": ["tests/test_agent_runtime.py"], "execution_approved": true')
    with pytest.raises(ValueError):
        _validate([row])

def test_rejects_duplicate_and_oversized_batches():
    with pytest.raises(ValueError): _validate([draft(), draft()])
    with pytest.raises(ValueError): _validate([draft()] * 5)

def test_label_preflight_failure_blocks_publication(monkeypatch):
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(subprocess.CalledProcessError):
        publish(_validate([draft()]), "nonkun12/line-bot")
    assert len(calls) == 1 and "labels/" in calls[0][2]

def test_duplicate_candidate_is_not_created(monkeypatch):
    body = draft()["body"]
    def fake(args, **kwargs):
        if args[:2] == ["gh", "api"] and "labels/" in args[2]:
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if args[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"body": body}), "")
        raise AssertionError("duplicate Issue must not be created")
    monkeypatch.setattr(subprocess, "run", fake)
    result = publish(_validate([draft()]), "nonkun12/line-bot")
    assert result["status"] == "ALL_DUPLICATES"
    assert result["execution_approval_granted"] is False

def test_creates_only_candidate_labeled_review_issue(monkeypatch):
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        if args[:2] == ["gh", "api"] and "labels/" in args[2]:
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if args[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "https://github.com/nonkun12/line-bot/issues/123", "")
    monkeypatch.setattr(subprocess, "run", fake)
    result = publish(_validate([draft()]), "nonkun12/line-bot")
    create = next(args for args in calls if args[:3] == ["gh", "issue", "create"])
    assert "--label" in create and "autonomous-task-candidate" in create
    assert result["execution_approval_granted"] is False
