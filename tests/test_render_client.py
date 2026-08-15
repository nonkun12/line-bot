import render_client


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

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
