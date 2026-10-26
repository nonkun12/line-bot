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
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", "1")
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

    with pytest.raises(mcp_client.McpNotReadyError):
        mcp_client._call_mcp_tool_once("save_memory", {"key": "k", "value": "v"})

    assert len(calls) == 2
    assert clock[0] == pytest.approx(1.0)


def test_hibernate_retry_default_wait_is_long(monkeypatch):
    monkeypatch.delenv("MCP_HIBERNATE_RETRY_MAX_SEC", raising=False)
    monkeypatch.delenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", raising=False)

    max_wait, interval = mcp_client._hibernate_retry_settings()

    assert max_wait == 120.0
    assert interval == 60.0


def test_mcp_request_logs_omit_argument_values_and_server_url(monkeypatch, capsys):
    private_value = "unit-test-private-value"
    server_url = "https://mcp.example.test/private-path"
    monkeypatch.setattr(mcp_client, "MCP_SERVER_URL", server_url)
    monkeypatch.setattr(mcp_client, "MCP_API_KEY", "unit-test-api-key")
    monkeypatch.setattr(mcp_client.httpx, "post", lambda *args, **kwargs: _success_response())

    result = mcp_client._call_mcp_tool_once(
        "save_memory", {"key": "private", "value": private_value}
    )

    output = capsys.readouterr().out
    assert result == "saved"
    assert private_value not in output
    assert server_url not in output
    assert "unit-test-api-key" not in output
    assert "tool_name=save_memory" in output
    assert "saved" not in output


def test_mcp_error_response_does_not_expose_upstream_message(monkeypatch, capsys):
    private_error = "unit-test-private-upstream-error"
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: _response(200, json_data={"error": private_error}),
    )

    with pytest.raises(RuntimeError, match="MCP server returned an error response") as exc_info:
        mcp_client._call_mcp_tool_once("save_memory", {"key": "k", "value": "v"})

    output = capsys.readouterr().out
    assert private_error not in output
    assert private_error not in str(exc_info.value)
