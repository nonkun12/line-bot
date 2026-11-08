import mcp_client
from agents.notes.handlers import handle_natural_note_search


def test_note_read_failure_is_explicit():
    def fail(tool, arguments):
        raise RuntimeError("temporary MCP failure")
    result = handle_natural_note_search("MCPでメモを検索して", "test-user", fail)
    assert "一時的に利用できません" in result
    assert "AIサービス" not in result


def test_note_search_normalizes_particle():
    seen = {}
    def fake(tool, arguments):
        seen.update(arguments)
        return []
    assert handle_natural_note_search("MCPでメモを検索して", "test-user", fake) == []
    assert seen["keyword"] == ""


def test_retry_settings_are_finite(monkeypatch):
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_MAX_SEC", "inf")
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", "nan")
    max_wait, interval = mcp_client._hibernate_retry_settings()
    assert max_wait == 120.0
    assert interval == 60.0


def test_only_one_hibernate_wake_owner():
    mcp_client._HIBERNATE_COOLDOWN_UNTIL = 0.0
    mcp_client._HIBERNATE_WAKE_OWNER = False
    assert mcp_client._claim_hibernate_wake() is True
    assert mcp_client._claim_hibernate_wake() is False
    mcp_client._release_hibernate_wake(0.0)


def test_dashboard_system_source_has_no_mcp_calls():
    from inspect import getsource
    from routes.dashboard import system_status
    source = getsource(system_status)
    assert "call_mcp_tool(" not in source


def test_render_health_probe_retries_generic_429_with_bounded_backoff(monkeypatch):
    import requests
    import render_client
    responses = []
    for status in (429, 200):
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = b'{"ok":true}' if status == 200 else b""
        response.url = "https://example.test/health"
        responses.append(response)
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(render_client, "_mcp_health_url", lambda: "https://example.test/health")
    monkeypatch.setattr(render_client.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(render_client.time, "monotonic", lambda: clock[0])
    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(render_client.time, "sleep", fake_sleep)
    assert render_client._mcp_http_is_hibernate_rate_limited() is False
    assert sleeps == [1.0]
    assert responses == []


def test_render_health_probe_stops_after_bounded_generic_429(monkeypatch):
    import requests
    import pytest
    import render_client
    calls = []
    def rate_limited(*args, **kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = 429
        response.url = "https://example.test/health"
        return response
    clock = [0.0]
    monkeypatch.setenv("MCP_HEALTH_429_MAX_SEC", "2")
    monkeypatch.setattr(render_client, "_mcp_health_url", lambda: "https://example.test/health")
    monkeypatch.setattr(render_client.requests, "get", rate_limited)
    monkeypatch.setattr(render_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(render_client.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(RuntimeError, match="bounded retry"):
        render_client._mcp_http_is_hibernate_rate_limited()
    assert len(calls) == 2
