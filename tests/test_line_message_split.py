"""LINE message size tests using the current shared Core gateway boundary."""
import pytest

import app
from core.gateway import AIResponse
from linebot.v3.messaging import TextMessage


def test_split_under_5000_is_one_message():
    text = "a" * 4999
    assert app.split_line_message(text) == [text]


def test_split_exactly_5000_is_one_message():
    text = "a" * 5000
    assert app.split_line_message(text) == [text]


def test_split_5001_is_two_messages():
    text = "a" * 5001
    result = app.split_line_message(text)
    assert result == ["a" * 5000, "a"]


def test_split_prefers_newline_position():
    text = ("a" * 4990) + "\n" + ("b" * 20)
    result = app.split_line_message(text)
    assert result == [("a" * 4990) + "\n", "b" * 20]
    assert "".join(result) == text


def test_split_without_newline_forces_5000_char_split():
    text = "x" * 12000
    result = app.split_line_message(text)
    assert all(len(chunk) <= 5000 for chunk in result)
    assert "".join(result) == text


def test_split_25000_is_exactly_five_messages_without_notice():
    text = "a" * 25000
    result = app.split_line_message(text)
    assert len(result) == 5
    assert "省略" not in result[-1]
    assert "".join(result) == text


def test_split_over_25000_truncates_with_notice():
    result = app.split_line_message("a" * 30000)
    assert len(result) == 5
    assert all(len(chunk) <= 5000 for chunk in result)
    assert "省略" in result[-1]


def test_split_empty_and_none():
    assert app.split_line_message("") == [""]
    assert app.split_line_message(None) == [""]


def test_build_line_messages_long_text():
    text = "z" * 12000
    messages = app._build_line_messages(text)
    assert len(messages) == 3
    assert all(isinstance(m, TextMessage) and len(m.text) <= 5000 for m in messages)
    assert "".join(m.text for m in messages) == text


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


def _mock_core_reply(monkeypatch, text):
    monkeypatch.setattr(
        app,
        "handle_channel_request",
        lambda *args, **kwargs: AIResponse(text=text),
    )
    monkeypatch.setattr(app, "save_message", lambda *args, **kwargs: None)


def test_process_and_reply_short_text_uses_shared_core(monkeypatch, capture_messaging_api):
    _mock_core_reply(monkeypatch, "短い返信")
    app._process_and_reply(_FakeEvent(), "user-123", "こんにちは")
    assert len(capture_messaging_api) == 1
    kind, request = capture_messaging_api[0]
    assert kind == "reply"
    assert request.messages[0].text == "短い返信"


def test_process_and_reply_long_text_splits_core_reply(monkeypatch, capture_messaging_api):
    long_reply = "g" * 12000
    _mock_core_reply(monkeypatch, long_reply)
    app._process_and_reply(_FakeEvent(), "user-123", "長い返信")
    assert len(capture_messaging_api) == 1
    kind, request = capture_messaging_api[0]
    assert kind == "reply"
    assert len(request.messages) == 3
    assert "".join(m.text for m in request.messages) == long_reply


def test_process_and_reply_falls_back_to_push_on_reply_failure(monkeypatch):
    long_reply = "h" * 11000

    class _FailingReplyThenPushApi:
        calls = []

        def __init__(self, api_client):
            pass

        def reply_message(self, request):
            raise RuntimeError("reply_token expired")

        def push_message(self, request):
            self.calls.append(("push", request))

    monkeypatch.setattr(app, "MessagingApi", _FailingReplyThenPushApi)
    _mock_core_reply(monkeypatch, long_reply)
    app._process_and_reply(_FakeEvent(), "user-456", "長文取得")
    assert len(_FailingReplyThenPushApi.calls) == 1
    kind, request = _FailingReplyThenPushApi.calls[0]
    assert kind == "push"
    assert len(request.messages) == 3
    assert "".join(m.text for m in request.messages) == long_reply


def test_internal_push_splits_long_message(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "save_message", lambda *args, **kwargs: None)
    long_message = "p" * 13000
    client = app.app.test_client()
    response = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": long_message},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )
    assert response.status_code == 200
    assert len(capture_messaging_api) == 1
    kind, request = capture_messaging_api[0]
    assert kind == "push"
    assert len(request.messages) == 3
    assert "".join(m.text for m in request.messages) == long_message


def test_internal_push_over_25000_chars_truncates(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "save_message", lambda *args, **kwargs: None)
    client = app.app.test_client()
    response = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": "q" * 30000},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )
    assert response.status_code == 200
    request = capture_messaging_api[0][1]
    assert len(request.messages) == 5
    assert "省略" in request.messages[-1].text
