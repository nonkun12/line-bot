import app as app_module


def test_process_and_reply_does_not_delegate_regular_messages_to_n8n(monkeypatch):
    calls = []

    monkeypatch.setattr(app_module, "N8N_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(
        app_module,
        "_delegate_to_n8n",
        lambda *args: calls.append(args) or True,
    )
    monkeypatch.setattr(app_module, "generate_reply", lambda user_id, message: "core reply")

    replies = []
    monkeypatch.setattr(
        app_module,
        "_line_reply",
        lambda reply_token, text: replies.append((reply_token, text)),
    )

    class Event:
        reply_token = "reply-token"

    app_module._process_and_reply(Event(), "u1", "東京の天気は？")

    assert calls == []
    assert replies == [("reply-token", "core reply")]
