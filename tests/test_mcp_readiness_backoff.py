import httpx
import pytest

import mcp_client


def _response(status_code, *, headers=None, json_data=None):
    request = httpx.Request("GET", "https://example.test/health")
    if json_data is not None:
        return httpx.Response(status_code, headers=headers, json=json_data, request=request)
    return httpx.Response(status_code, headers=headers, request=request)


def test_readiness_uses_exponential_backoff_for_hibernate(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK", "true")
    monkeypatch.setenv("MCP_READY_MAX_SEC", "180")
    monkeypatch.setenv("MCP_READY_POLL_SEC", "5")
    monkeypatch.setenv("MCP_READY_STABLE_COUNT", "2")

    clock = [0.0]
    sleeps = []
    responses = [
        _response(429, headers={"x-render-routing": "hibernate-rate-limited"}),
        _response(429, headers={"x-render-routing": "hibernate-rate-limited"}),
        _response(200, json_data={"ok": True}),
        _response(200, json_data={"ok": True}),
    ]

    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(mcp_client.time, "sleep", fake_sleep)
    monkeypatch.setattr(mcp_client.httpx, "get", lambda *args, **kwargs: responses.pop(0))

    mcp_client.wait_for_mcp_http_ready()

    assert sleeps == [5, 10, 20]
    assert responses == []


def test_readiness_backoff_remains_bounded(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK", "true")
    monkeypatch.setenv("MCP_READY_MAX_SEC", "35")
    monkeypatch.setenv("MCP_READY_POLL_SEC", "5")
    monkeypatch.setenv("MCP_READY_STABLE_COUNT", "1")

    clock = [0.0]
    sleeps = []
    calls = []

    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(mcp_client.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        mcp_client.httpx,
        "get",
        lambda *args, **kwargs: calls.append(1)
        or _response(429, headers={"x-render-routing": "hibernate-rate-limited"}),
    )

    with pytest.raises(mcp_client.McpNotReadyError):
        mcp_client.wait_for_mcp_http_ready()

    assert sleeps == [5, 10, 20]
    assert len(calls) == 4
    assert clock[0] == pytest.approx(35.0)
