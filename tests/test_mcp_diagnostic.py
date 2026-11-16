
import mcp_client


class FakeResponse:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body

    def close(self):
        pass


def test_diagnose_mcp_connection_passes_read_only_checks(monkeypatch):
    get_calls = []

    def fake_get(url, **kwargs):
        get_calls.append(url)
        return FakeResponse(200, {"ok": True})

    post_calls = []

    def fake_post(url, **kwargs):
        post_calls.append(kwargs["json"]["method"])
        return FakeResponse(200, {
            "jsonrpc": "2.0",
            "id": kwargs["json"]["id"],
            "result": {"tools": [{"name": "search_notes"}, {"name": "list_notes"}]},
        })

    monkeypatch.setattr(mcp_client.httpx, "get", fake_get)
    monkeypatch.setattr(mcp_client.httpx, "post", fake_post)

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "PASS"
    assert report["health"] == "PASS"
    assert report["ready"] == "PASS"
    assert report["mcp_auth"] == "PASS"
    assert report["tools_list"] == "PASS"
    assert report["tool_count"] == 2
    assert len(get_calls) == 2
    assert post_calls == ["tools/list"]


def test_diagnose_mcp_connection_fails_on_auth_error(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "get",
        lambda url, **kwargs: FakeResponse(200, {"ok": True}),
    )
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda url, **kwargs: FakeResponse(401, {"error": "Unauthorized"}),
    )

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "FAIL"
    assert report["mcp_auth"] == "FAIL (401)"
    assert report["tools_list"] == "FAIL (401)"
    assert report["tool_count"] == 0


def test_diagnose_mcp_connection_stops_when_database_not_ready(monkeypatch):
    post_calls = []

    def fake_get(url, **kwargs):
        if url.endswith("/health"):
            return FakeResponse(200, {"ok": True})
        return FakeResponse(503, {"ok": False, "status": "not_ready"})

    monkeypatch.setattr(mcp_client.httpx, "get", fake_get)
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda url, **kwargs: post_calls.append(kwargs["json"]["method"]),
    )

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "FAIL"
    assert report["health"] == "PASS"
    assert report["ready"] == "FAIL (503)"
    assert report["mcp_auth"] == "未確認"
    assert post_calls == []



def test_diagnose_retries_render_hibernate_429_once_after_delay(monkeypatch):
    get_calls = []
    sleep_calls = []

    def fake_get(url, **kwargs):
        get_calls.append(url)
        if url.endswith("/health") and get_calls.count(url) == 1:
            return FakeResponse(
                429, {},
                headers={"x-render-routing": "hibernate-rate-limited"},
            )
        return FakeResponse(200, {"ok": True})

    def fake_post(url, **kwargs):
        return FakeResponse(200, {
            "jsonrpc": "2.0",
            "id": kwargs["json"]["id"],
            "result": {"tools": [{"name": "search_notes"}]},
        })

    monkeypatch.setattr(mcp_client.httpx, "get", fake_get)
    monkeypatch.setattr(mcp_client.httpx, "post", fake_post)
    monkeypatch.setattr(mcp_client.time, "sleep", sleep_calls.append)

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "PASS"
    assert report["health"] == "PASS"
    assert len(get_calls) == 3  # health 429, health retry, then /ready
    assert sleep_calls == [65.0]


def test_diagnose_stops_after_one_failed_hibernate_retry(monkeypatch):
    get_calls = []
    sleep_calls = []

    def fake_get(url, **kwargs):
        get_calls.append(url)
        return FakeResponse(
            429, {},
            headers={"x-render-routing": "hibernate-rate-limited"},
        )

    monkeypatch.setattr(mcp_client.httpx, "get", fake_get)
    monkeypatch.setattr(mcp_client.time, "sleep", sleep_calls.append)

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "FAIL"
    assert report["health"] == "FAIL (429)"
    assert report["ready"] == "未確認"
    assert report["mcp_auth"] == "未確認"
    assert len(get_calls) == 2
    assert sleep_calls == [65.0]
