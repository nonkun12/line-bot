import pytest

import scripts.hermes_queue_worker as worker


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def _issue(number=7, approval="not_approved", queue_state="pending"):
    return {
        "number": number,
        "title": "Hermes task " + "a" * 32,
        "state": "open",
        "body": (
            "- requester_user_id: U123\n"
            f"- queue_state: {queue_state}\n"
            f"- approval_state: {approval}\n"
            "## Instruction\n"
            "do not print this private instruction"
        ),
    }


def test_classify_issue_hides_instruction_and_blocks_unapproved(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    result = worker.classify_issue(_issue())
    assert result == {
        "task_id": "a" * 32,
        "issue_number": "7",
        "requester_user_id": "U123",
        "state": "blocked_not_approved",
    }
    assert "instruction" not in str(result).lower()


def test_classify_approved_pending_issue_is_ready_for_manual_approval(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    result = worker.classify_issue(_issue(approval="approved"))
    assert result["state"] == "ready_for_manual_approval"


def test_classify_non_pending_issue_is_not_requeued(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    result = worker.classify_issue(_issue(approval="approved", queue_state="claimed"))
    assert result["state"] == "blocked_claimed"


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
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
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
        worker.fetch_queue(token="", repository="nonkun12/ai-dispatch-queue")
    with pytest.raises(worker.WorkerConfigurationError):
        worker.fetch_queue(token="token", repository="someone/else")


def test_fetch_queue_does_not_leak_github_error_body(monkeypatch):
    monkeypatch.setattr(worker.httpx, "get", lambda *args, **kwargs: _Response(status_code=403))
    with pytest.raises(worker.WorkerFetchError, match="HTTP 403") as error:
        worker.fetch_queue(token="secret-token", repository="nonkun12/ai-dispatch-queue")
    assert "secret-token" not in str(error.value)


def test_claim_rejects_unapproved_without_patching(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    calls = []
    monkeypatch.setattr(worker.httpx, "get", lambda *args, **kwargs: _Response(payload=_issue()))
    monkeypatch.setattr(worker.httpx, "patch", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(worker.ClaimRejected, match="approval"):
        worker.claim_approved_issue(
            7, worker_id="mac-worker-1", token="token", repository="nonkun12/ai-dispatch-queue"
        )
    assert calls == []


def test_claim_updates_only_approved_pending_issue_and_does_not_execute(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    calls = {}

    def fake_get(url, **kwargs):
        return _Response(payload=_issue(approval="approved"))

    def fake_patch(url, **kwargs):
        calls.update(kwargs)
        return _Response(payload={"number": 7})

    monkeypatch.setattr(worker.httpx, "get", fake_get)
    monkeypatch.setattr(worker.httpx, "patch", fake_patch)
    result = worker.claim_approved_issue(
        7, worker_id="mac-worker-1", token="token", repository="nonkun12/ai-dispatch-queue"
    )
    assert result == {
        "task_id": "a" * 32,
        "issue_number": "7",
        "state": "claimed_not_executed",
    }
    body = calls["json"]["body"]
    assert "- queue_state: claimed" in body
    assert "- worker_id: mac-worker-1" in body
    assert "do not print this private instruction" in body
    assert calls["headers"]["Authorization"] == "Bearer token"


def test_claim_rejects_already_claimed_issue(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    monkeypatch.setattr(
        worker.httpx, "get",
        lambda *args, **kwargs: _Response(payload=_issue(approval="approved", queue_state="claimed"))
    )
    with pytest.raises(worker.ClaimRejected, match="pending"):
        worker.claim_approved_issue(
            7, worker_id="mac-worker-1", token="token", repository="nonkun12/ai-dispatch-queue"
        )


def test_single_worker_lock_excludes_second_process_lock_handle(tmp_path):
    lock_path = tmp_path / "worker.lock"
    with worker.single_worker_lock(lock_path):
        with pytest.raises(worker.WorkerAlreadyRunning):
            with worker.single_worker_lock(lock_path):
                pass

def test_claim_holds_single_worker_lock_for_read_and_update(monkeypatch, tmp_path):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    from contextlib import contextmanager

    lock_state = {"held": False}

    @contextmanager
    def fake_lock(lock_path=None):
        assert lock_state["held"] is False
        lock_state["held"] = True
        try:
            yield
        finally:
            lock_state["held"] = False

    def fake_get(url, **kwargs):
        assert lock_state["held"] is True
        return _Response(payload=_issue(approval="approved"))

    def fake_patch(url, **kwargs):
        assert lock_state["held"] is True
        return _Response(payload={"number": 7})

    monkeypatch.setattr(worker, "single_worker_lock", fake_lock)
    monkeypatch.setattr(worker.httpx, "get", fake_get)
    monkeypatch.setattr(worker.httpx, "patch", fake_patch)

    result = worker.claim_approved_issue(
        7,
        worker_id="mac-worker-1",
        token="token",
        repository="nonkun12/ai-dispatch-queue",
        lock_path=tmp_path / "worker.lock",
    )

    assert result["state"] == "claimed_not_executed"
    assert lock_state["held"] is False



def test_classify_blocks_unallowlisted_requester_and_empty_allowlist(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U999")
    assert worker.classify_issue(_issue(approval="approved"))["state"] == "blocked_invalid_metadata"
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "")
    assert worker.classify_issue(_issue(approval="approved"))["state"] == "blocked_invalid_metadata"


@pytest.mark.parametrize("metadata", [
    "- requester_user_id: U123\n- requester_user_id: U123",
    "- approval_state: approved\n- approval_state: approved",
    "- queue_state: pending\n- queue_state: pending",
])
def test_classify_blocks_duplicate_security_metadata(monkeypatch, metadata):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    issue = _issue(approval="approved")
    body = issue["body"]
    if metadata.startswith("- requester"):
        body = body.replace("- requester_user_id: U123", metadata)
    elif metadata.startswith("- approval"):
        body = body.replace("- approval_state: approved", metadata)
    else:
        body = body.replace("- queue_state: pending", metadata)
    issue["body"] = body
    assert worker.classify_issue(issue)["state"] == "blocked_invalid_metadata"


def test_claim_rejects_unallowlisted_or_missing_allowlist_without_patch(monkeypatch):
    calls = []
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "")
    monkeypatch.setattr(worker.httpx, "get", lambda *args, **kwargs: _Response(payload=_issue(approval="approved")))
    monkeypatch.setattr(worker.httpx, "patch", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(worker.ClaimRejected, match="allowlisted"):
        worker.claim_approved_issue(
            7, worker_id="mac-worker-1", token="token", repository="nonkun12/ai-dispatch-queue"
        )
    assert calls == []


def test_worker_rejects_different_queue_repository():
    with pytest.raises(worker.WorkerConfigurationError, match="private queue"):
        worker.fetch_queue(token="token", repository="attacker/public")

def test_claim_rejects_unallowlisted_requester_without_patch(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U999")
    calls = []
    monkeypatch.setattr(
        worker.httpx, "get",
        lambda *args, **kwargs: _Response(payload=_issue(approval="approved")),
    )
    monkeypatch.setattr(worker.httpx, "patch", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(worker.ClaimRejected, match="allowlisted"):
        worker.claim_approved_issue(
            7, worker_id="mac-worker-1", token="token",
            repository="nonkun12/ai-dispatch-queue",
        )
    assert calls == []


@pytest.mark.parametrize("duplicate_line", [
    "- requester_user_id: U123",
    "- approval_state: approved",
    "- queue_state: pending",
])
def test_claim_rejects_duplicate_security_metadata_without_patch(monkeypatch, duplicate_line):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    issue = _issue(approval="approved")
    issue["body"] += f"\n{duplicate_line}"
    calls = []
    monkeypatch.setattr(worker.httpx, "get", lambda *args, **kwargs: _Response(payload=issue))
    monkeypatch.setattr(worker.httpx, "patch", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(worker.ClaimRejected):
        worker.claim_approved_issue(
            7, worker_id="mac-worker-1", token="token",
            repository="nonkun12/ai-dispatch-queue",
        )
    assert calls == []
