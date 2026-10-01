from types import SimpleNamespace

import agents.normal.handlers as handlers


def _response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=text, tool_calls=[])
        )]
    )


def test_normal_agent_injects_user_memory(monkeypatch):
    calls = []

    def call_mcp_tool(name, arguments):
        calls.append((name, arguments))
        return '[{"key": "name", "value": "太郎"}]'

    prompts = []

    def fake_generate_chat_completion(*, messages, **kwargs):
        prompts.append(messages[0]["content"])
        return _response("こんにちは、太郎さん。")

    monkeypatch.setattr(handlers, "load_history", lambda user_id: [])
    monkeypatch.setattr(handlers, "save_message", lambda *args: None)
    monkeypatch.setattr(handlers, "generate_chat_completion", fake_generate_chat_completion)

    reply = handlers.handle_normal_message("こんにちは", "user123", call_mcp_tool)

    assert reply == "こんにちは、太郎さん。"
    assert calls == [("get_all_memory", {"user_id": "user123"})]
    assert "太郎" in prompts[0]
    assert "【このユーザーについて既に記憶している情報】" in prompts[0]


def test_normal_agent_does_not_claim_memory_is_empty_when_retrieval_fails(monkeypatch):
    prompts = []

    def call_mcp_tool(name, arguments):
        assert name == "get_all_memory"
        assert arguments == {"user_id": "user123"}
        raise RuntimeError("memory backend unavailable")

    def fake_generate_chat_completion(*, messages, **kwargs):
        prompts.append(messages[0]["content"])
        return _response("通常回答")

    monkeypatch.setattr(handlers, "load_history", lambda user_id: [])
    monkeypatch.setattr(handlers, "save_message", lambda *args: None)
    monkeypatch.setattr(handlers, "generate_chat_completion", fake_generate_chat_completion)

    reply = handlers.handle_normal_message("こんにちは", "user123", call_mcp_tool)

    assert reply == "通常回答"
    assert prompts
    assert "記憶サービスを取得できませんでした" in prompts[0]
    assert "記憶の有無を推測しないでください" in prompts[0]
    assert "(まだ何も記憶していません)" not in prompts[0]
