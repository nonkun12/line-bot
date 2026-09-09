import os

from agents.deploy.node import deploy_node


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def base_state():
    return {
        "commit_result": {"committed": True, "hash": "abc123"},
        "publish_result": {"published": True, "pr": {"number": 42}},
        "agent_results": {},
    }


def test_deploy_waits_when_pr_not_merged(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("AUTO_DEPLOY", "true")
    monkeypatch.setattr(
        "agents.deploy.node.requests.get",
        lambda *args, **kwargs: FakeResponse(
            200,
            {"number": 42, "state": "open", "merged": False, "html_url": "https://github.com/x/y/pull/42"},
        ),
    )
    triggered = []
    monkeypatch.setattr("agents.deploy.node.trigger_deploy", lambda: triggered.append(True))

    result = deploy_node(base_state())

    assert result["deploy_result"]["pending"] is True
    assert result["deploy_result"]["waiting_for_merge"] is True
    assert triggered == []


def test_deploy_requires_merge_before_auto_deploy(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("AUTO_DEPLOY", "true")
    monkeypatch.setattr(
        "agents.deploy.node.requests.get",
        lambda *args, **kwargs: FakeResponse(
            200,
            {"number": 42, "state": "closed", "merged": True, "html_url": "https://github.com/x/y/pull/42", "merge_commit_sha": "merge123"},
        ),
    )
    monkeypatch.setattr(
        "agents.deploy.node.trigger_deploy",
        lambda: {"triggered": True, "deploy_id": "dep-1", "status": "queued"},
    )

    result = deploy_node(base_state())

    assert result["deploy_result"]["deployed"] is True
    assert result["deploy_result"]["merged"] is True
    assert result["deploy_result"]["pr"]["merge_commit_sha"] == "merge123"


def test_deploy_stays_pending_when_pr_lookup_fails(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("AUTO_DEPLOY", "true")
    monkeypatch.setattr(
        "agents.deploy.node.requests.get",
        lambda *args, **kwargs: FakeResponse(500, {"message": "server error"}),
    )
    triggered = []
    monkeypatch.setattr("agents.deploy.node.trigger_deploy", lambda: triggered.append(True))

    result = deploy_node(base_state())

    assert result["deploy_result"]["pending"] is True
    assert result["deploy_result"]["waiting_for_merge"] is True
    assert triggered == []
