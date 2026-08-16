"""app._process_and_reply() のn8n委譲分岐のテスト。

- N8N_WEBHOOK_URL が設定されている場合、_delegate_to_n8n が呼ばれ、
  ローカルの generate_reply / reply_message / push_message は
  呼ばれないこと。
- N8N_WEBHOOK_URL が未設定(空文字)の場合、従来通りローカルの
  generate_reply 経路がそのまま動くこと(既存動作の回帰確認)。
"""
import pytest

import app


class _FakeEvent:
    def __init__(self, reply_token="dummy-reply-token"):
        self.reply_token = reply_token


class _CapturingMessagingApi:
    """MessagingApi(api) の呼び出しを記録するフェイク。"""
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

    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "https://example.com/webhook/line-in")
    monkeypatch.setattr(app, "_delegate_to_n8n", fake_delegate)

    # ローカル生成経路が万一呼ばれた場合に検知できるよう例外にしておく
    def fail_generate_reply(user_id, text):
        raise AssertionError("generate_reply should not be called when delegating to n8n")

    monkeypatch.setattr(app, "generate_reply", fail_generate_reply)

    event = _FakeEvent()
    app._process_and_reply(event, "user-123", "こんにちは")

    assert delegate_calls == [("user-123", "こんにちは", "https://example.com/webhook/line-in", 5)]
    # LINEへの直接返信(reply/push)はline-bot側では行われない
    assert capture_messaging_api == []


def test_process_and_reply_uses_local_path_when_webhook_url_unset(monkeypatch, capture_messaging_api):
    def fail_delegate(*args, **kwargs):
        raise AssertionError("_delegate_to_n8n should not be called when N8N_WEBHOOK_URL is unset")

    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(app, "_delegate_to_n8n", fail_delegate)
    monkeypatch.setattr(app, "generate_reply", lambda user_id, text: "短い返信")
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    event = _FakeEvent()
    app._process_and_reply(event, "user-123", "こんにちは")

    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "reply"
    assert request.messages[0].text == "短い返信"
