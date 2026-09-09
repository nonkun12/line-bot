"""app._process_and_reply() のn8n委譲分岐のテスト。"""
import pytest
import app

class _FakeEvent:
    def __init__(self, reply_token="dummy-reply-token"):
        self.reply_token = reply_token

class _CapturingMessagingApi:
    calls = []
    def __init__(self, api_client):
        pass
    def reply_message(self, request):
        _CapturingMessagingApi.calls.append(("reply", request))
    def push_message(self, request):
        _CapturingMessagingApi.calls.append(("push", request))

@pytest.fixture
def capture_messaging_api(monkeypatch):
    _CapturingMessagingApi.calls = []
    monkeypatch.setattr(app, "MessagingApi", _CapturingMessagingApi)
    yield _CapturingMessagingApi.calls

def test_process_and_reply_delegates_to_n8n_when_webhook_url_set(monkeypatch, capture_messaging_api):
    delegate_calls = []
    def fake_delegate(user_id, message, webhook_url, timeout=5):
        delegate_calls.append((user_id, message, webhook_url, timeout))
        return True
    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "https://example.com/webhook/line-in")
    monkeypatch.setattr(app, "_delegate_to_n8n", fake_delegate)
    monkeypatch.setattr(app, "generate_reply", lambda *args: (_ for _ in ()).throw(AssertionError("generate_reply should not be called when delegating to n8n")))
    app._process_and_reply(_FakeEvent(), "user-123", "こんにちは")
    assert delegate_calls == [("user-123", "こんにちは", "https://example.com/webhook/line-in", 5)]
    assert capture_messaging_api == []

def test_process_and_reply_uses_local_path_when_webhook_url_unset(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(app, "_delegate_to_n8n", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_delegate_to_n8n should not be called when N8N_WEBHOOK_URL is unset")))
    monkeypatch.setattr(app, "generate_reply", lambda user_id, text: "短い返信")
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)
    app._process_and_reply(_FakeEvent(), "user-123", "こんにちは")
    assert len(capture_messaging_api) == 1
    kind, request = capture_messaging_api[0]
    assert kind == "reply"
    assert request.messages[0].text == "短い返信"
