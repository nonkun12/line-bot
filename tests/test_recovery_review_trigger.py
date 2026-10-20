import json
from unittest.mock import patch

import recovery_review_trigger as trigger


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_non_review_command_is_ignored():
    assert trigger.request_recovery_resume_review("u1", "こんにちは") == (False, "")


def test_review_command_requires_exact_safe_task_id(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = trigger.request_recovery_resume_review(
        "u1", "Recovery AI再開レビュー確認 task_id=task/unsafe reviewed=true"
    )
    assert handled is True
    assert "形式が正しくありません" in reply


def test_review_command_requires_allowlisted_user(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = trigger.request_recovery_resume_review(
        "u2", "Recovery AI再開レビュー確認 task_id=task-a reviewed=true"
    )
    assert handled is True
    assert "許可されていません" in reply


def test_review_command_requires_github_token(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = trigger.request_recovery_resume_review(
        "u1", "Recovery AI再開レビュー確認 task_id=task-a reviewed=true"
    )
    assert handled is True
    assert "認証未設定" in reply


def test_review_command_dispatches_state_only_workflow(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client(_Response(204))
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_recovery_resume_review(
            "u1", "Recovery AI再開レビュー確認 task_id=task-a reviewed=true"
        )
    assert handled is True
    assert "タスクは実行されません" in reply
    assert client.calls[0][0][0].endswith(
        "/actions/workflows/recovery-ai-resume-review.yml/dispatches"
    )
    assert client.calls[0][1]["json"] == {
        "ref": "main",
        "inputs": {"task_id": "task-a"},
    }


def test_review_command_reports_permission_failure(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    with patch.object(trigger.httpx, "Client", return_value=_Client(_Response(403))):
        handled, reply = trigger.request_recovery_resume_review(
            "u1", "Recovery AI再開レビュー確認 task_id=task-a reviewed=true"
        )
    assert handled is True
    assert "GitHub権限不足" in reply
