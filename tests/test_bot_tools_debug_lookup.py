from bot_tools import MCP_TOOLS_SCHEMA, dispatch_tool_call


def test_debug_lookup_registered_in_schema():
    names = [tool["function"]["name"] for tool in MCP_TOOLS_SCHEMA]
    assert "debug_lookup" in names

    debug_tool = next(
        tool for tool in MCP_TOOLS_SCHEMA if tool["function"]["name"] == "debug_lookup"
    )
    assert debug_tool["function"]["parameters"]["required"] == ["query"]
    assert "query" in debug_tool["function"]["parameters"]["properties"]


def test_dispatch_tool_call_debug_lookup_passes_query_to_debug_agent(monkeypatch):
    calls = []

    def fake_debug_agent_node(state):
        calls.append(state)
        return {
            **state,
            "agent_results": {
                "debug": {
                    "text": "原因: timeout\n\n修正案: retry"
                }
            },
        }

    monkeypatch.setattr("agents.debug.node.debug_agent_node", fake_debug_agent_node)

    result = dispatch_tool_call(
        "user123",
        "debug_lookup",
        {"query": "HTTP 500が発生しました"},
    )

    assert calls == [
        {
            "raw_message": "HTTP 500が発生しました",
            "agent_results": {},
        }
    ]
    assert result == "原因: timeout\n\n修正案: retry"


def test_dispatch_tool_call_debug_lookup_returns_fallback_when_result_missing(monkeypatch):
    monkeypatch.setattr(
        "agents.debug.node.debug_agent_node",
        lambda state: {**state, "agent_results": {}},
    )

    result = dispatch_tool_call(
        "user456",
        "debug_lookup",
        {"query": "unknown error"},
    )

    assert result == "Debug Agentの解析結果を取得できませんでした。"


def test_dispatch_tool_call_debug_lookup_missing_query_defaults_to_empty_string(monkeypatch):
    calls = []

    def fake_debug_agent_node(state):
        calls.append(state)
        return {
            **state,
            "agent_results": {
                "debug": {"text": "Debug Agentに解析対象がありません。"}
            },
        }

    monkeypatch.setattr("agents.debug.node.debug_agent_node", fake_debug_agent_node)

    result = dispatch_tool_call("user789", "debug_lookup", {})

    assert calls == [
        {
            "raw_message": "",
            "agent_results": {},
        }
    ]
    assert result == "Debug Agentに解析対象がありません。"
