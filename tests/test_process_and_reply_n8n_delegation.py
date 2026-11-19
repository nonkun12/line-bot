"""Regular LINE conversations use the shared Core gateway, not n8n."""

import pytest

import app
from core.gateway import AIResponse


class _FakeEvent:
    reply_token = "dummy-reply-token"


class _CapturingMessagingApi:
    calls = []

    def __init__(self, api_client):
        pass

    def reply_message(self, request):
        self.calls.append(("reply", request))

    def push_message(self, request):
        self.calls.append(("push", request))


@pytest.fixture
def capture_messaging_api(monkeypatch):
    _CapturingMessagingApi.calls = []
    monkeypatch.setattr(app, "MessagingApi", _CapturingMessagingApi)
    yield _CapturingMessagingApi.calls


def test_process_and_reply_never_delegates_regular_messages_to_n8n(monkeypatch, capture_messaging_api):
    delegate_calls = []
    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "https://example.com/webhook/line-in")
    monkeypatch.setattr(app, "_delegate_to_n8n", lambda *args, **kwargs: delegate_calls.append(args))
    monkeypatch.setattr(app, "handle_channel_request", lambda *args, **kwargs: AIResponse(text="Core返信"))
    monkeypatch.setattr(app, "save_message", lambda *args, **kwargs: None)

    app._process_and_reply(_FakeEvent(), "user-123", "こんにちは")

    assert delegate_calls == []
    assert len(capture_messaging_api) == 1
    assert capture_messaging_api[0][0] == "reply"
    assert capture_messaging_api[0][1].messages[0].text == "Core返信"


def test_process_and_reply_uses_core_even_when_n8n_url_unset(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(app, "_delegate_to_n8n", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("n8n must not be called")))
    monkeypatch.setattr(app, "handle_channel_request", lambda *args, **kwargs: AIResponse(text="Core返信"))
    monkeypatch.setattr(app, "save_message", lambda *args, **kwargs: None)

    app._process_and_reply(_FakeEvent(), "user-123", "こんにちは")

    assert len(capture_messaging_api) == 1
    assert capture_messaging_api[0][1].messages[0].text == "Core返信"
