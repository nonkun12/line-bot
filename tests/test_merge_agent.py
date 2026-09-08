from agents.merge.node import merge_approved_pr, merge_node


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def base_state():
    return {
        "commit_result": {"committed": True, "hash": "abc123", "branch": "worker/job-42"},
        "publish_result": {
            "published": True,
            "branch": "worker/job-42",
            "pr": {"number": 42},
        },
        "agent_results": {},
    }


def test_merge_approved_pr_merges_and_rechecks_state(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    responses = iter([
        FakeResponse(200, {
            "number": 42,
            "state": "open",
            "merged": False,
            "head": {"ref": "worker/job-42", "sha": "abc123"},
            "base": {"ref": "main"},
            "html_url": "https://github.com/x/y/pull/42",
        }),
        FakeResponse(200, {"merged": True, "sha": "merge123", "message": "Pull Request successfully merged"}),
        FakeResponse(200, {
            "number": 42,
            "state": "closed",
            "merged": True,
            "head": {"ref": "worker/job-42", "sha": "abc123"},
            "base": {"ref": "main"},
            "merge_commit_sha": "merge123",
            "html_url": "https://github.com/x/y/pull/42",
        }),
    ])
    monkeypatch.setattr("agents.merge.node.requests.get", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr("agents.merge.node.requests.put", lambda *args, **kwargs: next(responses))

    result = merge_approved_pr(base_state())

    assert result["merged"] is True
    assert result["pr"]["merged"] is True
    assert result["pr"]["merge_commit_sha"] == "merge123"


def test_merge_approved_pr_rejects_wrong_head_commit(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.merge.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {
            "number": 42,
            "state": "open",
            "merged": False,
            "head": {"ref": "worker/job-42", "sha": "different"},
            "base": {"ref": "main"},
        }),
    )

    result = merge_approved_pr(base_state())

    assert result["merged"] is False
    assert "head commit" in result["error"]


def test_merge_node_returns_failure_when_pr_is_not_open(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "agents.merge.node.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"number": 42, "state": "closed", "merged": False}),
    )

    result = merge_node(base_state())

    assert result["merge_result"]["merged"] is False
    assert "not open" in result["merge_result"]["error"]
