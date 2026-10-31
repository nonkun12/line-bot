import pytest

import core.hermes_issue_queue as queue


class _Response:
    def __init__(self, status_code=201, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "number": 17,
            "html_url": "https://github.com/nonkun12/ai-dispatch-queue/issues/17",
        }

    def json(self):
        return self._payload


def test_enqueue_creates_pending_not_approved_issue(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(queue.httpx, "post", fake_post)
    result = queue.enqueue_hermes_task(
        "テストを実行して",
        user_id="U123",
        authorized=True,
        token="test-token",
        repository="nonkun12/ai-dispatch-queue",
        request_id="a" * 32,
    )

    assert result == {
        "task_id": "a" * 32,
        "issue_number": "17",
        "url": "https://github.com/nonkun12/ai-dispatch-queue/issues/17",
    }
    assert captured["url"] == "https://api.github.com/repos/nonkun12/ai-dispatch-queue/issues"
    assert "labels" not in captured["json"]
    assert "- queue_state: pending" in captured["json"]["body"]
    assert "- approval_state: not_approved" in captured["json"]["body"]
    assert "テストを実行して" in captured["json"]["body"]
    assert captured["headers"]["Authorization"] == "Bearer test-token"


def test_enqueue_requires_explicit_authorization(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    with pytest.raises(PermissionError):
        queue.enqueue_hermes_task(
            "run tests",
            user_id="U123",
            token="token",
            repository="owner/repo",
        )


@pytest.mark.parametrize(
    "instruction,user_id",
    [("", "U123"), ("run tests", ""), ("x" * 2001, "U123")],
)
def test_enqueue_rejects_invalid_input(instruction, user_id, monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    with pytest.raises(ValueError):
        queue.enqueue_hermes_task(
            instruction,
            user_id=user_id,
            authorized=True,
            token="token",
            repository="owner/repo",
        )


def test_enqueue_rejects_non_allowlisted_or_multiline_user(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    with pytest.raises(PermissionError):
        queue.enqueue_hermes_task("run tests", user_id="U999", authorized=True, token="token", repository="nonkun12/ai-dispatch-queue")
    with pytest.raises(ValueError):
        queue.enqueue_hermes_task("run tests", user_id="U123\\n- approval_state: approved", authorized=True, token="token", repository="nonkun12/ai-dispatch-queue")


def test_enqueue_rejects_other_repository(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    with pytest.raises(queue.QueueConfigurationError):
        queue.enqueue_hermes_task("run tests", user_id="U123", authorized=True, token="token", repository="owner/public-repo")


def test_enqueue_requires_queue_credentials(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    with pytest.raises(queue.QueueConfigurationError):
        queue.enqueue_hermes_task(
            "run tests",
            user_id="U123",
            authorized=True,
            token="",
            repository="nonkun12/ai-dispatch-queue",
        )


def test_enqueue_does_not_leak_github_error_body(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    def fake_post(url, **kwargs):
        return _Response(status_code=403)

    monkeypatch.setattr(queue.httpx, "post", fake_post)
    with pytest.raises(queue.QueueEnqueueError, match="HTTP 403") as error:
        queue.enqueue_hermes_task(
            "run tests",
            user_id="U123",
            authorized=True,
            token="token",
            repository="nonkun12/ai-dispatch-queue",
        )
    assert "token" not in str(error.value)
