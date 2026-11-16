import mcp_client


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

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
        if kwargs["json"]["method"] == "initialize":
            return FakeResponse(200, {"jsonrpc": "2.0", "id": kwargs["json"]["id"], "result": {"protocolVersion": "2025-03-26"}})
        return FakeResponse(200, {"jsonrpc": "2.0", "id": kwargs["json"]["id"], "result": {"tools": [{"name": "search_notes"}, {"name": "list_notes"}]}})

    monkeypatch.setattr(mcp_client.httpx, "get", fake_get)
    monkeypatch.setattr(mcp_client.httpx, "post", fake_post)

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "PASS"
    assert report["health"] == "PASS"
    assert report["ready"] == "PASS"
    assert report["initialize"] == "PASS"
    assert report["tools_list"] == "PASS"
    assert report["tool_count"] == 2
    assert len(get_calls) == 2
    assert post_calls == ["initialize", "tools/list"]


def test_diagnose_mcp_connection_stops_on_auth_failure(monkeypatch):
    post_calls = []

    monkeypatch.setattr(
        mcp_client.httpx,
        "get",
        lambda url, **kwargs: FakeResponse(200, {"ok": True}),
    )

    def fake_post(url, **kwargs):
        post_calls.append(kwargs["json"]["method"])
        return FakeResponse(401, {"error": "Unauthorized"})

    monkeypatch.setattr(mcp_client.httpx, "post", fake_post)

    report = mcp_client.diagnose_mcp_connection()

    assert report["status"] == "FAIL"
    assert report["initialize"] == "FAIL (401)"
    assert report["tools_list"] == "未確認"
    assert report["tool_count"] == 0
    assert post_calls == ["initialize"]


def test_diagnose_mcp_connection_stops_when_database_not_ready(monkeypatch):
    get_calls = []
    post_calls = []

    def fake_get(url, **kwargs):
        get_calls.append(url)
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
    assert report["initialize"] == "未確認"
    assert post_calls == []
