from agents.deploy.node import deploy_node


def test_deploy_node_skips_when_commit_not_completed():
    state = {
        "agent_results": {},
        "commit_result": {"committed": False},
    }

    result = deploy_node(state)

    deploy_result = result["agent_results"]["deploy"]

    assert deploy_result["deployed"] is False
    assert deploy_result["skipped"] is True
    assert deploy_result["reason"] == "commit not completed"


def test_deploy_node_pending_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_DEPLOY", raising=False)

    state = {
        "agent_results": {},
        "commit_result": {"committed": True, "hash": "abc123"},
    }

    result = deploy_node(state)

    deploy_result = result["agent_results"]["deploy"]

    assert deploy_result["deployed"] is False
    assert deploy_result["pending"] is True
    assert deploy_result["reason"] == "waiting for manual approval"
    assert deploy_result["commit_hash"] == "abc123"


def test_deploy_node_pending_when_auto_deploy_explicitly_false(monkeypatch):
    monkeypatch.setenv("AUTO_DEPLOY", "false")

    state = {
        "agent_results": {},
        "commit_result": {"committed": True, "hash": "abc123"},
    }

    result = deploy_node(state)

    deploy_result = result["agent_results"]["deploy"]

    assert deploy_result["deployed"] is False
    assert deploy_result["pending"] is True


def test_deploy_node_triggers_real_deploy_when_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_DEPLOY", "true")

    def fake_trigger_deploy():
        return {
            "triggered": True,
            "deploy_id": "dep-999",
            "status": "created",
            "error": None,
        }

    monkeypatch.setattr(
        "agents.deploy.node.trigger_deploy",
        fake_trigger_deploy,
    )

    state = {
        "agent_results": {},
        "commit_result": {"committed": True, "hash": "abc123"},
    }

    result = deploy_node(state)

    deploy_result = result["agent_results"]["deploy"]

    assert deploy_result["deployed"] is True
    assert deploy_result["pending"] is False
    assert deploy_result["deploy_id"] == "dep-999"
    assert deploy_result["commit_hash"] == "abc123"


def test_deploy_node_handles_trigger_failure_when_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_DEPLOY", "true")

    def fake_trigger_deploy():
        return {
            "triggered": False,
            "deploy_id": None,
            "status": None,
            "error": "RENDER_API_KEY が設定されていません",
        }

    monkeypatch.setattr(
        "agents.deploy.node.trigger_deploy",
        fake_trigger_deploy,
    )

    state = {
        "agent_results": {},
        "commit_result": {"committed": True, "hash": "abc123"},
    }

    result = deploy_node(state)

    deploy_result = result["agent_results"]["deploy"]

    assert deploy_result["deployed"] is False
    assert deploy_result["pending"] is False
    assert deploy_result["reason"] == "RENDER_API_KEY が設定されていません"
