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
