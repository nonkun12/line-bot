from agents.review.node import check_review_status, review_node


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def state():
    return {
        "job_id": 99,
        "commit_result": {"committed": True, "hash": "abc123", "branch": "worker/job-99"},
        "publish_result": {"published": True, "commit_hash": "abc123", "branch": "worker/job-99", "pr": {"number": 99}},
        "agent_results": {},
        "workdir": "/tmp/job-99",
    }


def github_runs():
    return [
        {"name": "Pytest", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "Overnight Worker Test", "status": "completed", "conclusion": "success", "id": 2},
        {"name": "AI Code Review", "status": "completed", "conclusion": "success", "id": 3},
    ]


def test_review_waits_for_missing_checks(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": []}),
    )

    result = check_review_status(state())

    assert result["status"] == "pending"
    assert set(result["missing"]) == {"Pytest", "Overnight Worker Test", "AI Code Review"}


def test_review_passes_only_when_all_required_workflows_and_ai_review_pass(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": github_runs()}),
    )
    monkeypatch.setattr("agents.review.node._review_diff", lambda state: "diff")
    monkeypatch.setattr(
        "agents.review.node._call_ai_review",
        lambda diff: {"verdict": "PASS", "summary": "No blocking issues", "findings": []},
    )

    result = check_review_status(state())

    assert result["status"] == "passed"
    assert result["github"]["head_sha"] == "abc123"
    assert result["ai_review"]["verdict"] == "PASS"


def test_review_fails_when_required_workflow_fails(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    runs = github_runs()
    runs[1]["conclusion"] = "failure"
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": runs}),
    )

    result = review_node(state())

    assert result["review_result"]["status"] == "failed"
    assert result["agent_results"]["review"]["failed"] == ["Overnight Worker Test"]


def test_review_fails_when_ai_review_rejects(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": github_runs()}),
    )
    monkeypatch.setattr("agents.review.node._review_diff", lambda state: "diff")
    monkeypatch.setattr(
        "agents.review.node._call_ai_review",
        lambda diff: {
            "verdict": "FAIL",
            "summary": "Blocking security issue",
            "findings": [{"severity": "blocking", "file": "app.py", "detail": "unsafe change"}],
        },
    )

    result = check_review_status(state())

    assert result["status"] == "failed"
    assert result["ai_review"]["verdict"] == "FAIL"


def test_review_configuration_error_is_terminal(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": github_runs()}),
    )
    monkeypatch.setattr("agents.review.node._review_diff", lambda state: "diff")

    def fail_config(_diff):
        raise RuntimeError("GROQ_API_KEY is not configured for Worker AI review")

    monkeypatch.setattr("agents.review.node._call_ai_review", fail_config)

    result = review_node(state())

    assert result["review_result"]["status"] == "failed"
    assert "GROQ_API_KEY" in result["review_result"]["reason"]


def test_review_fails_on_missing_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    result = review_node(state())

    assert result["review_result"] == {
        "status": "failed",
        "reason": "review agent error: GITHUB_TOKEN is not configured",
    }
