from unittest.mock import MagicMock

from bot_tools import MCP_TOOLS_SCHEMA, dispatch_tool_call


def test_sheets_lookup_registered_in_schema():
    names = [tool["function"]["name"] for tool in MCP_TOOLS_SCHEMA]
    assert "sheets_lookup" in names

    sheets_tool = next(
        tool for tool in MCP_TOOLS_SCHEMA if tool["function"]["name"] == "sheets_lookup"
    )
    assert sheets_tool["function"]["parameters"]["required"] == ["query"]
    assert "query" in sheets_tool["function"]["parameters"]["properties"]


def test_dispatch_tool_call_sheets_lookup_calls_handle_sheets_message(monkeypatch):
    calls = []
    fake_client = MagicMock()

    monkeypatch.setattr(
        "agents.sheets.client.GoogleSheetsClient",
        lambda spreadsheet_id=None: fake_client,
    )

    def fake_handle_sheets_message(query, user_id, client):
        calls.append((query, user_id, client))
        return {"text": "検索結果：1件", "rows": [["foo"]], "success": True}

    monkeypatch.setattr(
        "agents.sheets.handlers.handle_sheets_message",
        fake_handle_sheets_message,
    )

    result = dispatch_tool_call(
        "user123",
        "sheets_lookup",
        {"query": "シートから検索 foo"},
    )

    assert calls == [("シートから検索 foo", "user123", fake_client)]
    assert result == "検索結果：1件"


def test_dispatch_tool_call_sheets_lookup_returns_text_field_only(monkeypatch):
    monkeypatch.setattr(
        "agents.sheets.client.GoogleSheetsClient",
        lambda spreadsheet_id=None: MagicMock(),
    )
    monkeypatch.setattr(
        "agents.sheets.handlers.handle_sheets_message",
        lambda query, user_id, client: {
            "text": "Google Sheetsに記録しました：テストデータ",
            "success": True,
        },
    )

    result = dispatch_tool_call(
        "user456",
        "sheets_lookup",
        {"query": "テストデータを記録して"},
    )

    assert result == "Google Sheetsに記録しました：テストデータ"


def test_dispatch_tool_call_sheets_lookup_handles_none_result(monkeypatch):
    monkeypatch.setattr(
        "agents.sheets.client.GoogleSheetsClient",
        lambda spreadsheet_id=None: MagicMock(),
    )
    monkeypatch.setattr(
        "agents.sheets.handlers.handle_sheets_message",
        lambda query, user_id, client: None,
    )

    result = dispatch_tool_call(
        "user789",
        "sheets_lookup",
        {"query": ""},
    )

    assert result == "Google Sheetsの操作を理解できませんでした。"


def test_dispatch_tool_call_sheets_lookup_missing_query_defaults_to_empty_string(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "agents.sheets.client.GoogleSheetsClient",
        lambda spreadsheet_id=None: MagicMock(),
    )

    def fake_handle_sheets_message(query, user_id, client):
        calls.append(query)
        return None

    monkeypatch.setattr(
        "agents.sheets.handlers.handle_sheets_message",
        fake_handle_sheets_message,
    )

    result = dispatch_tool_call("user000", "sheets_lookup", {})

    assert calls == [""]
    assert result == "Google Sheetsの操作を理解できませんでした。"
