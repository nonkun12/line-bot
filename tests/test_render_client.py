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
