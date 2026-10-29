"""Regression tests for normal-agent MCP tool exposure."""

from types import SimpleNamespace

from agents.normal import handlers


def test_search_notes_is_exposed_to_groq_tool_schema():
    names = {
        tool.get("function", {}).get("name")
        for tool in handlers._NORMAL_MCP_TOOLS_SCHEMA
    }
    assert "search_notes" in names


def test_search_notes_is_allowed_by_normal_agent_dispatch_gate():
    assert "search_notes" in handlers._NORMAL_MCP_TOOL_NAMES
    assert "search_notes" in handlers._SAFE_INLINE_TOOLS


def test_search_notes_is_safe_read_only_fallback():
    assert "search_notes" in handlers._SAFE_FALLBACK_TOOLS


def test_normal_agent_executes_search_notes_tool_call(monkeypatch):
    calls = []
    tool_call = SimpleNamespace(
        id="notes-search-1",
        function=SimpleNamespace(
            name="search_notes",
            arguments='{"query": "LINE Bot"}',
        ),
    )
    first = SimpleNamespace(content="", tool_calls=[tool_call])
    final = SimpleNamespace(content="LINE Botのメモが見つかりました。", tool_calls=None)
    responses = iter([
        SimpleNamespace(choices=[SimpleNamespace(message=first)]),
        SimpleNamespace(choices=[SimpleNamespace(message=final)]),
    ])

    monkeypatch.setattr(
        handlers,
        "generate_chat_completion",
        lambda **kwargs: next(responses),
    )
    monkeypatch.setattr(handlers, "load_history", lambda user_id: [])
    monkeypatch.setattr(handlers, "save_message", lambda *args, **kwargs: None)

    def dispatch(user_id, tool_name, args, original_message=None):
        calls.append((user_id, tool_name, args, original_message))
        return '[{"title": "LINE Bot開発", "body": "検索機能の修正"}]'

    monkeypatch.setattr(handlers, "dispatch_tool_call", dispatch)

    reply = handlers.handle_normal_message(
        "LINE Botのメモを検索して",
        "test-user",
        lambda *args, **kwargs: None,
    )

    assert reply == "LINE Botのメモが見つかりました。"
    assert calls == [
        ("test-user", "search_notes", {"query": "LINE Bot"}, "LINE Botのメモを検索して")
    ]
