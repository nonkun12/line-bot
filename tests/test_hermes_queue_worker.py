import pytest

import scripts.hermes_queue_worker as worker


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def _issue(number=7, approval="not_approved"):
    return {
        "number": number,
        "title": "Hermes task " + "a" * 32,
        "state": "open",
        "body": (
            "- requester_user_id: U123\n"
            f"- approval_state: {approval}\n"
            "## Instruction\n"
            "do not print this private instruction"
        ),
    }


def test_classify_issue_hides_instruction_and_blocks_unapproved():
    result = worker.classify_issue(_issue())
    assert result == {
        "task_id": "a" * 32,
        "issue_number": "7",
        "requester_user_id": "U123",
        "state": "blocked_not_approved",
    }
    assert "instruction" not in str(result).lower()


def test_classify_approved_issue_only_marks_ready_for_manual_approval():
    result = worker.classify_issue(_issue(approval="approved"))
    assert result["state"] == "ready_for_manual_approval"


def test_classify_ignores_non_queue_and_pull_request_items():
    assert worker.classify_issue({"title": "ordinary issue", "state": "open"}) is None
    issue = _issue()
    issue["pull_request"] = {"url": "https://api.github.com/example"}
    assert worker.classify_issue(issue) is None


def test_classify_blocks_malformed_metadata():
    issue = _issue()
    issue["body"] = "no queue metadata"
    assert worker.classify_issue(issue)["state"] == "blocked_invalid_metadata"


def test_fetch_queue_uses_read_only_get_and_returns_sorted_safe_metadata(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(payload=[_issue(9), _issue(3, approval="approved"),
                                  {"title": "not a task", "state": "open"}])

    monkeypatch.setattr(worker.httpx, "get", fake_get)
    result = worker.fetch_queue(token="test-token", repository="nonkun12/ai-dispatch-queue")
    assert [task["issue_number"] for task in result] == ["3", "9"]
    assert captured["url"].endswith("/repos/nonkun12/ai-dispatch-queue/issues")
    assert captured["params"] == {"state": "open", "per_page": 50}
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert "json" not in captured


def test_fetch_queue_requires_token_and_valid_repository():
    with pytest.raises(worker.WorkerConfigurationError):
        worker.fetch_queue(token="", repository="owner/repo")
    with pytest.raises(worker.WorkerConfigurationError):
        worker.fetch_queue(token="token", repository="owner/repo/extra")


def test_fetch_queue_does_not_leak_github_error_body(monkeypatch):
    monkeypatch.setattr(worker.httpx, "get", lambda *args, **kwargs: _Response(status_code=403))
    with pytest.raises(worker.WorkerFetchError, match="HTTP 403") as error:
        worker.fetch_queue(token="secret-token", repository="owner/repo")
    assert "secret-token" not in str(error.value)
