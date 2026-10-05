import render_client


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_get_render_logs_without_api_key(monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)

    result = render_client.get_render_logs()

    assert result == "RENDER_API_KEY が設定されていません"


def test_get_render_logs_sends_expected_params(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "dummy-key")

    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        captured["timeout"] = timeout
        return _FakeResponse({"logs": [{"message": "line1"}, {"message": "line2"}]})

    monkeypatch.setattr(render_client.requests, "get", fake_get)

    result = render_client.get_render_logs()

    assert captured["url"] == "https://api.render.com/v1/logs"
    assert captured["headers"]["Authorization"] == "Bearer dummy-key"
    assert captured["params"] == {
        "resource": render_client.SERVICE_ID,
        "ownerId": render_client.OWNER_ID,
        "limit": 20,
        "type": "app",
    }
    assert captured["timeout"] == 10
    assert result == "line1\nline2"


def test_trigger_deploy_without_api_key(monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)

    result = render_client.trigger_deploy()

    assert result["triggered"] is False
    assert result["deploy_id"] is None
    assert "RENDER_API_KEY" in result["error"]


def test_trigger_deploy_success(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "dummy-key")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert "deploys" in url
        assert headers["Authorization"] == "Bearer dummy-key"
        return _FakeResponse({"id": "dep-123", "status": "created"})

    monkeypatch.setattr(render_client.requests, "post", fake_post)

    result = render_client.trigger_deploy()

    assert result["triggered"] is True
    assert result["deploy_id"] == "dep-123"
    assert result["status"] == "created"
    assert result["error"] is None


def test_trigger_deploy_http_error(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "dummy-key")

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({}, status_code=500)

    monkeypatch.setattr(render_client.requests, "post", fake_post)

    result = render_client.trigger_deploy()

    assert result["triggered"] is False
    assert result["deploy_id"] is None
    assert result["error"] is not None


def test_mcp_service_session_disabled_does_not_touch_render(monkeypatch):
    monkeypatch.delenv("MCP_RENDER_ON_DEMAND", raising=False)

    def fail(*args, **kwargs):
        raise AssertionError("Render API must not be called when disabled")

    monkeypatch.setattr(render_client, "get_service", fail)
    with render_client.mcp_service_session():
        pass


def test_mcp_service_session_rejects_line_bot_service_id(monkeypatch):
    monkeypatch.setenv("MCP_RENDER_ON_DEMAND", "true")
    monkeypatch.setenv("MCP_RENDER_SERVICE_ID", render_client.SERVICE_ID)

    try:
        with render_client.mcp_service_session():
            pass
    except RuntimeError as exc:
        assert "LINE-bot" in str(exc)
    else:
        raise AssertionError("Expected dedicated MCP service ID validation")


def test_mcp_service_session_resumes_then_suspends(monkeypatch):
    monkeypatch.setenv("MCP_RENDER_ON_DEMAND", "true")
    monkeypatch.setenv("MCP_RENDER_SERVICE_ID", "srv-mcp123")

    states = iter([
        {"suspended": "suspended"},
        {"suspended": "not_suspended"},
    ])
    calls = []

    monkeypatch.setattr(render_client, "get_service", lambda service_id: next(states))
    monkeypatch.setattr(
        render_client,
        "resume_service",
        lambda service_id: calls.append(("resume", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "suspend_service",
        lambda service_id: calls.append(("suspend", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "wait_for_service_running",
        lambda service_id: calls.append(("wait", service_id)) or {},
    )

    with render_client.mcp_service_session():
        calls.append(("work",))

    assert calls == [
        ("resume", "srv-mcp123"),
        ("wait", "srv-mcp123"),
        ("work",),
        ("suspend", "srv-mcp123"),
    ]


def test_mcp_service_session_leaves_already_running_service_alone(monkeypatch):
    monkeypatch.setenv("MCP_RENDER_ON_DEMAND", "true")
    monkeypatch.setenv("MCP_RENDER_SERVICE_ID", "srv-mcp123")

    calls = []
    monkeypatch.setattr(
        render_client,
        "get_service",
        lambda service_id: {"suspended": "not_suspended"},
    )
    monkeypatch.setattr(
        render_client,
        "resume_service",
        lambda service_id: calls.append(("resume", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "suspend_service",
        lambda service_id: calls.append(("suspend", service_id)) or {},
    )

    with render_client.mcp_service_session():
        calls.append(("work",))

    assert calls == [("work",)]


def test_mcp_service_session_suspends_after_operation_failure(monkeypatch):
    monkeypatch.setenv("MCP_RENDER_ON_DEMAND", "true")
    monkeypatch.setenv("MCP_RENDER_SERVICE_ID", "srv-mcp123")

    calls = []
    states = iter([
        {"suspended": "suspended"},
        {"suspended": "not_suspended"},
    ])
    monkeypatch.setattr(render_client, "get_service", lambda service_id: next(states))
    monkeypatch.setattr(
        render_client,
        "resume_service",
        lambda service_id: calls.append(("resume", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "suspend_service",
        lambda service_id: calls.append(("suspend", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "wait_for_service_running",
        lambda service_id: calls.append(("wait", service_id)) or {},
    )

    try:
        with render_client.mcp_service_session():
            raise ValueError("operation failed")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected operation failure")

    assert calls == [
        ("resume", "srv-mcp123"),
        ("suspend", "srv-mcp123"),
    ]


def test_mcp_service_session_suspends_when_startup_wait_fails(monkeypatch):
    monkeypatch.setenv("MCP_RENDER_ON_DEMAND", "true")
    monkeypatch.setenv("MCP_RENDER_SERVICE_ID", "srv-mcp123")

    calls = []
    monkeypatch.setattr(
        render_client,
        "get_service",
        lambda service_id: {"suspended": "suspended"},
    )
    monkeypatch.setattr(
        render_client,
        "resume_service",
        lambda service_id: calls.append(("resume", service_id)) or {},
    )
    monkeypatch.setattr(
        render_client,
        "wait_for_service_running",
        lambda service_id: (_ for _ in ()).throw(RuntimeError("startup timeout")),
    )
    monkeypatch.setattr(
        render_client,
        "suspend_service",
        lambda service_id: calls.append(("suspend", service_id)) or {},
    )

    try:
        with render_client.mcp_service_session():
            raise AssertionError("MCP operation must not run before startup succeeds")
    except RuntimeError as exc:
        assert "startup timeout" in str(exc)

    assert calls == [
        ("resume", "srv-mcp123"),
        ("suspend", "srv-mcp123"),
    ]


def test_get_service_uses_service_endpoint(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "dummy-key")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers, timeout=timeout)
        return _FakeResponse({"id": "srv-mcp123", "suspended": "suspended"})

    monkeypatch.setattr(render_client.requests, "get", fake_get)

    result = render_client.get_service("srv-mcp123")

    assert captured["url"] == "https://api.render.com/v1/services/srv-mcp123"
    assert captured["headers"]["Authorization"] == "Bearer dummy-key"
    assert captured["timeout"] == 10
    assert result["suspended"] == "suspended"


def test_resume_and_suspend_use_exact_service_endpoint(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "dummy-key")
    urls = []

    def fake_post(url, headers=None, timeout=None, json=None):
        urls.append((url, headers["Authorization"], timeout))
        return _FakeResponse({})

    monkeypatch.setattr(render_client.requests, "post", fake_post)

    render_client.resume_service("srv-mcp123")
    render_client.suspend_service("srv-mcp123")

    assert urls == [
        ("https://api.render.com/v1/services/srv-mcp123/resume", "Bearer dummy-key", 15),
        ("https://api.render.com/v1/services/srv-mcp123/suspend", "Bearer dummy-key", 15),
    ]
