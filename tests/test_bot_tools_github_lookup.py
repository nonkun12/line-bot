from bot_tools import MCP_TOOLS_SCHEMA, dispatch_tool_call


def test_github_lookup_registered_in_schema():
    names = [tool["function"]["name"] for tool in MCP_TOOLS_SCHEMA]
    assert "github_lookup" in names

    github_tool = next(
        tool for tool in MCP_TOOLS_SCHEMA if tool["function"]["name"] == "github_lookup"
    )
    assert github_tool["function"]["parameters"]["required"] == ["query"]
    assert "query" in github_tool["function"]["parameters"]["properties"]


def test_dispatch_tool_call_github_lookup_calls_handle_github_message(monkeypatch):
    calls = []

    def fake_handle_github_message(query, user_id):
        calls.append((query, user_id))
        return "fake github result"

    monkeypatch.setattr(
        "agents.github.handlers.handle_github_message",
        fake_handle_github_message,
    )

    result = dispatch_tool_call(
        "user123",
        "github_lookup",
        {"query": "最新コミットを教えて"},
    )

    assert calls == [("最新コミットを教えて", "user123")]
    assert result == "fake github result"


def test_dispatch_tool_call_github_lookup_returns_value_unchanged(monkeypatch):
    monkeypatch.setattr(
        "agents.github.handlers.handle_github_message",
        lambda query, user_id: "【Latest Commits】\n- abc1234: fix bug",
    )

    result = dispatch_tool_call(
        "user456",
        "github_lookup",
        {"query": "commit historyを見せて"},
    )

    assert result == "【Latest Commits】\n- abc1234: fix bug"


def test_dispatch_tool_call_github_lookup_missing_query_defaults_to_empty_string(monkeypatch):
    calls = []

    def fake_handle_github_message(query, user_id):
        calls.append(query)
        return "GitHub Agentに質問してください。"

    monkeypatch.setattr(
        "agents.github.handlers.handle_github_message",
        fake_handle_github_message,
    )

    result = dispatch_tool_call("user789", "github_lookup", {})

    assert calls == [""]
    assert result == "GitHub Agentに質問してください。"
