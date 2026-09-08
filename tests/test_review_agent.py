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
    }


def test_review_waits_for_missing_checks(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": []}),
    )

    result = check_review_status(state())

    assert result["status"] == "pending"
    assert set(result["missing"]) == {"Pytest", "Overnight Worker Test", "AI Code Review"}


def test_review_passes_only_when_all_required_workflows_succeed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    runs = [
        {"name": "Pytest", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "Overnight Worker Test", "status": "completed", "conclusion": "success", "id": 2},
        {"name": "AI Code Review", "status": "completed", "conclusion": "success", "id": 3},
    ]
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": runs}),
    )

    result = check_review_status(state())

    assert result["status"] == "passed"
    assert result["head_sha"] == "abc123"


def test_review_fails_when_required_workflow_fails(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    runs = [
        {"name": "Pytest", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "Overnight Worker Test", "status": "completed", "conclusion": "failure", "id": 2},
        {"name": "AI Code Review", "status": "completed", "conclusion": "success", "id": 3},
    ]
    monkeypatch.setattr(
        "agents.review.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"workflow_runs": runs}),
    )

    result = review_node(state())

    assert result["review_result"]["status"] == "failed"
    assert result["agent_results"]["review"]["failed"] == ["Overnight Worker Test"]
