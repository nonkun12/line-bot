import app


def _headers():
    return {"x-internal-key": app.INTERNAL_PUSH_KEY}


def test_internal_ask_runs_real_gateway_graph_and_notes_node(monkeypatch):
    calls = []

    def fake_call_mcp_tool(tool_name, arguments, timeout=3.0):
        calls.append((tool_name, arguments))
        if tool_name == "save_note":
            return "メモ「テスト」を保存しました。"
        raise AssertionError(f"unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(app, "call_mcp_tool", fake_call_mcp_tool)

    response = app.app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "メモにテストを保存して"},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert "【Notes】" in body["reply"]
    assert "メモ「テスト」を保存しました。" in body["reply"]
    assert calls == [
        (
            "save_note",
            {
                "user_id": "u1",
                "title": "LINEメモ",
                "body": "テスト",
                "category": "一般",
            },
        )
    ]
