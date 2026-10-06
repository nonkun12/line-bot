import httpx
import pytest

import mcp_client


@pytest.fixture(autouse=True)
def reset_hibernate_state():
    mcp_client._HIBERNATE_COOLDOWN_UNTIL = 0.0
    mcp_client._HIBERNATE_WAKE_OWNER = False
    yield
    mcp_client._HIBERNATE_COOLDOWN_UNTIL = 0.0
    mcp_client._HIBERNATE_WAKE_OWNER = False


def _response(status_code, *, headers=None, json_data=None):
    request = httpx.Request("POST", "https://example.test/mcp")
    if json_data is not None:
        return httpx.Response(status_code, headers=headers, json=json_data, request=request)
    return httpx.Response(status_code, headers=headers, request=request)


def _success_response():
    return _response(
        200,
        headers={"content-type": "application/json"},
        json_data={"result": {"content": [{"type": "text", "text": "saved"}]}},
    )


def test_hibernate_429_retries_and_succeeds(monkeypatch):
    calls = []
    responses = [
        _response(429, headers={"x-render-routing": "hibernate-rate-limited"}),
        _success_response(),
    ]

    monkeypatch.setenv("MCP_HIBERNATE_RETRY_MAX_SEC", "5")
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", "0.1")
    monkeypatch.setattr(mcp_client.httpx, "post", lambda *args, **kwargs: calls.append(1) or responses.pop(0))
    monkeypatch.setattr(mcp_client.time, "sleep", lambda _: None)

    result = mcp_client._call_mcp_tool_once("save_memory", {"key": "k", "value": "v"})

    assert result == "saved"
    assert len(calls) == 2


def test_non_hibernate_429_does_not_retry(monkeypatch):
    calls = []

    monkeypatch.setenv("MCP_HIBERNATE_RETRY_MAX_SEC", "5")
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: calls.append(1) or _response(429),
    )

    with pytest.raises(httpx.HTTPStatusError):
        mcp_client._call_mcp_tool_once("save_memory", {"key": "k", "value": "v"})

    assert len(calls) == 1


def test_hibernate_retry_is_bounded(monkeypatch):
    calls = []
    clock = [0.0]

    monkeypatch.setenv("MCP_HIBERNATE_RETRY_MAX_SEC", "1")
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", "0.4")
    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(mcp_client.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: calls.append(1)
        or _response(429, headers={"x-render-routing": "hibernate-rate-limited"}),
    )

    with pytest.raises(httpx.HTTPStatusError):
        mcp_client._call_mcp_tool_once("save_memory", {"key": "k", "value": "v"})

    assert len(calls) == 3
    assert clock[0] == pytest.approx(0.8)


def test_hibernate_retry_default_wait_is_long(monkeypatch):
    monkeypatch.delenv("MCP_HIBERNATE_RETRY_MAX_SEC", raising=False)
    monkeypatch.delenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", raising=False)

    max_wait, interval = mcp_client._hibernate_retry_settings()

    assert max_wait == 120.0
    assert interval == 60.0
