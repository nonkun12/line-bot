from core.gateway import AIResponse
import app as app_module


def test_process_and_reply_does_not_delegate_regular_messages_to_n8n(monkeypatch):
    calls = []
    replies = []

    monkeypatch.setattr(app_module, "N8N_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(app_module, "_delegate_to_n8n", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        app_module,
        "handle_channel_request",
        lambda *args, **kwargs: AIResponse(text="core reply"),
    )
    monkeypatch.setattr(app_module, "_line_reply", lambda token, text: replies.append((token, text)))
    monkeypatch.setattr(app_module, "save_message", lambda *args, **kwargs: None)

    class Event:
        reply_token = "reply-token"

    app_module._process_and_reply(Event(), "u1", "東京の天気は？")

    assert calls == []
    assert replies == [("reply-token", "core reply")]
