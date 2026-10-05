from types import SimpleNamespace

import agents.normal.handlers as handlers


def test_normal_chat_does_not_implicitly_read_memory(monkeypatch):
    calls = []

    def fail_if_mcp_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("normal chat must not call MCP implicitly")

    choice = SimpleNamespace(content="こんにちは！", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=choice)])

    monkeypatch.setattr(handlers, "generate_chat_completion", lambda **kwargs: response)
    monkeypatch.setattr(handlers, "load_history", lambda user_id: [])
    monkeypatch.setattr(handlers, "save_message", lambda *args, **kwargs: None)

    reply = handlers.handle_normal_message(
        "こんにちは",
        "test-user",
        fail_if_mcp_called,
    )

    assert reply == "こんにちは！"
    assert calls == []



def test_normal_agent_schema_excludes_memory_and_notes_tools():
    names = {
        tool["function"]["name"]
        for tool in handlers._NORMAL_MCP_TOOLS_SCHEMA
    }
    assert "get_all_memory" not in names
    assert "get_memory" not in names
    assert "search_notes" not in names
    assert "save_memory" not in names
    assert names == {"set_reminder", "list_reminders", "cancel_reminder"}


def test_normal_agent_rejects_forged_memory_tool_call(monkeypatch):
    calls = []

    forged = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="forged-1",
                function=SimpleNamespace(
                    name="get_all_memory",
                    arguments="{}",
                ),
            )
        ],
    )
    final = SimpleNamespace(content="通常会話として返答しました。", tool_calls=None)
    responses = iter([
        SimpleNamespace(choices=[SimpleNamespace(message=forged)]),
        SimpleNamespace(choices=[SimpleNamespace(message=final)]),
    ])

    monkeypatch.setattr(handlers, "generate_chat_completion", lambda **kwargs: next(responses))
    monkeypatch.setattr(handlers, "load_history", lambda user_id: [])
    monkeypatch.setattr(handlers, "save_message", lambda *args, **kwargs: None)

    def fail_if_mcp_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("forged memory tool call must be rejected")

    reply = handlers.handle_normal_message(
        "こんにちは",
        "test-user",
        fail_if_mcp_called,
    )

    assert reply == "通常会話として返答しました。"
    assert calls == []
