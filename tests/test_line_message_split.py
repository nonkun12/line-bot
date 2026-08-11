"""
LINE Messaging APIの「1メッセージ最大5000文字」制限対策のテスト。

対象:
- app.split_line_message() の分割ロジック単体
- app._build_line_messages() のTextMessage変換
- app._process_and_reply() (reply_message / push_messageフォールバック経路)
- app.internal_ai_report / app.internal_push エンドポイント (push_message経路)
- GitHub Agentが返す長文結果が最終的に正しく分割されること

LINE APIそのものには接続せず、MessagingApi.reply_message / push_message を
monkeypatchしてモック化する。
"""
import json

import pytest

import app
from linebot.v3.messaging import TextMessage


# =========================================================
# split_line_message() 単体テスト
# =========================================================

def test_split_under_5000_is_one_message():
    text = "a" * 4999
    result = app.split_line_message(text)
    assert result == [text]
    assert len(result) == 1


def test_split_exactly_5000_is_one_message():
    text = "a" * 5000
    result = app.split_line_message(text)
    assert result == [text]
    assert len(result) == 1


def test_split_5001_is_two_messages():
    text = "a" * 5001
    result = app.split_line_message(text)
    assert len(result) == 2
    assert all(len(chunk) <= 5000 for chunk in result)
    # 改行がないため機械的に5000文字ちょうどで切られる
    assert result[0] == "a" * 5000
    assert result[1] == "a" * 1


def test_split_10000_is_two_messages():
    text = "a" * 10000
    result = app.split_line_message(text)
    assert len(result) == 2
    assert all(len(chunk) <= 5000 for chunk in result)
    assert result[0] == "a" * 5000
    assert result[1] == "a" * 5000


def test_split_prefers_newline_position():
    # 4990文字 + 改行 + 20文字 = 5011文字。5000文字以内(先頭側)に改行があるので
    # 5000文字目で機械的に割るのではなく、改行位置で分割されるはず。
    text = ("a" * 4990) + "\n" + ("b" * 20)
    result = app.split_line_message(text)
    assert len(result) == 2
    # 改行はチャンクの境界として使われ、前側チャンクの末尾に残る(内容を欠落させない)
    assert result[0] == ("a" * 4990) + "\n"
    assert result[1] == "b" * 20
    assert "\n" not in result[1]
    assert len(result[0]) <= 5000
    # 結合すると元のテキストに一致する(改行を含め内容が失われていない)
    assert "".join(result) == text


def test_split_without_newline_forces_5000_char_split():
    text = "x" * 12000  # 改行なし
    result = app.split_line_message(text)
    assert all(len(chunk) <= 5000 for chunk in result)
    assert "".join(result) == text


def test_split_25000_or_less_is_at_most_5_messages():
    text = "a" * 25000
    result = app.split_line_message(text)
    assert len(result) <= 5
    assert len(result) == 5
    assert all(len(chunk) <= 5000 for chunk in result)
    # 25000文字ちょうどなので省略通知は付かない
    assert "省略" not in result[-1]
    assert "".join(result) == text


def test_split_over_25000_truncates_with_notice():
    text = "a" * 30000
    result = app.split_line_message(text)
    assert len(result) == 5
    assert all(len(chunk) <= 5000 for chunk in result)
    # 最後のメッセージに省略の旨が付与されている
    assert "省略" in result[-1]


def test_split_over_25000_every_message_within_limit():
    text = "b" * 40000
    result = app.split_line_message(text)
    assert len(result) <= 5
    for chunk in result:
        assert len(chunk) <= 5000


def test_split_empty_string_unchanged():
    result = app.split_line_message("")
    assert result == [""]


def test_split_none_unchanged():
    result = app.split_line_message(None)
    assert result == [""]


def test_split_short_normal_reply_regression():
    text = "こんにちは、元気ですか？"
    result = app.split_line_message(text)
    assert result == [text]


# =========================================================
# _build_line_messages() : TextMessageへの変換
# =========================================================

def test_build_line_messages_short_text():
    messages = app._build_line_messages("短い返信です")
    assert len(messages) == 1
    assert isinstance(messages[0], TextMessage)
    assert messages[0].text == "短い返信です"


def test_build_line_messages_long_text_splits_into_multiple_textmessage():
    text = "z" * 12000  # 改行なし。5000文字ごとに機械分割 -> 5000+5000+2000で3件
    messages = app._build_line_messages(text)
    assert len(messages) == 3
    assert all(isinstance(m, TextMessage) for m in messages)
    assert all(len(m.text) <= 5000 for m in messages)
    assert "".join(m.text for m in messages) == text


def test_build_line_messages_empty_text():
    messages = app._build_line_messages("")
    assert len(messages) == 1
    assert messages[0].text == ""


# =========================================================
# reply_message() 経路: app._process_and_reply()
# =========================================================

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


def test_process_and_reply_short_text_sends_single_reply_message(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "generate_reply", lambda user_id, text: "短い返信")
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    event = _FakeEvent()
    app._process_and_reply(event, "user-123", "こんにちは")

    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "reply"
    assert len(request.messages) == 1
    assert request.messages[0].text == "短い返信"


def test_process_and_reply_long_text_splits_reply_message(monkeypatch, capture_messaging_api):
    long_reply = "g" * 12000  # 改行なし -> 5000+5000+2000で3件
    monkeypatch.setattr(app, "generate_reply", lambda user_id, text: long_reply)
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    event = _FakeEvent()
    app._process_and_reply(event, "user-123", "長いファイルを見せて")

    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "reply"
    assert len(request.messages) == 3
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "".join(m.text for m in request.messages) == long_reply


def test_process_and_reply_falls_back_to_push_on_reply_failure_and_splits(monkeypatch):
    """reply_messageが失敗した場合、push_messageへフォールバックし、
    かつフォールバック先でも5000文字分割が適用されることを確認する。"""
    long_reply = "h" * 11000  # 改行なし -> 5000+5000+1000で3件

    class _FailingReplyThenPushApi:
        calls = []

        def __init__(self, api_client):
            pass

        def reply_message(self, request):
            raise RuntimeError("reply_token expired")

        def push_message(self, request):
            _FailingReplyThenPushApi.calls.append(("push", request))

    _FailingReplyThenPushApi.calls = []
    monkeypatch.setattr(app, "MessagingApi", _FailingReplyThenPushApi)
    monkeypatch.setattr(app, "generate_reply", lambda user_id, text: long_reply)
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    event = _FakeEvent()
    app._process_and_reply(event, "user-456", "長文取得")

    calls = _FailingReplyThenPushApi.calls
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 3
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "".join(m.text for m in request.messages) == long_reply


# =========================================================
# push_message() 経路: /internal/ai-report, /internal/push
# =========================================================

def test_internal_ai_report_push_message_splits_long_report(monkeypatch, capture_messaging_api):
    long_report = "r" * 12000  # 改行なし -> 5000+5000+2000で3件
    monkeypatch.setattr(app, "generate_ai_secretary_report", lambda user_id: long_report)
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    client = app.app.test_client()
    resp = client.post(
        "/internal/ai-report",
        json={"user_id": "U_test_user"},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )

    assert resp.status_code == 200
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 3
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "".join(m.text for m in request.messages) == long_report


def test_internal_ai_report_short_report_single_message(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "generate_ai_secretary_report", lambda user_id: "本日の報告は以上です")
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    client = app.app.test_client()
    resp = client.post(
        "/internal/ai-report",
        json={"user_id": "U_test_user"},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )

    assert resp.status_code == 200
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 1
    assert request.messages[0].text == "本日の報告は以上です"


def test_internal_push_splits_long_message(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    long_message = "p" * 13000
    client = app.app.test_client()
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": long_message},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )

    assert resp.status_code == 200
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 3
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "".join(m.text for m in request.messages) == long_message


def test_internal_push_short_message_single_message_regression(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    client = app.app.test_client()
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": "リマインダーです"},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )

    assert resp.status_code == 200
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 1
    assert request.messages[0].text == "リマインダーです"


def test_internal_push_over_25000_chars_truncates_with_notice(monkeypatch, capture_messaging_api):
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    huge_message = "q" * 30000
    client = app.app.test_client()
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": huge_message},
        headers={"x-internal-key": app.INTERNAL_PUSH_KEY},
    )

    assert resp.status_code == 200
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert len(request.messages) == 5
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "省略" in request.messages[-1].text


# =========================================================
# GitHub Agentの長文結果が最終的に正しく分割されること
# =========================================================

def test_github_long_file_content_is_split_for_line(monkeypatch, capture_messaging_api):
    """GitHubファイル内容取得(handle_file_contents)が5000文字超の結果を
    返した場合、generate_reply()経由でLINE送信直前に正しく分割されることを確認する。
    agents/github/handlers.py 自体は変更せず、GitHubClientだけをフェイクに差し替える。
    """
    from agents.github import handlers as github_handlers

    long_file_content = "def foo():\n    pass\n" * 400  # 5000文字超

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_file_contents(self, path):
            return long_file_content

    monkeypatch.setattr(github_handlers, "GitHubClient", FakeClient)

    # generate_reply()内のLangGraph呼び出しをスキップし、GitHub Agentの
    # 結果だけがそのままfinal replyとして返る状況を再現する。
    def fake_invoke_graph(user_id, message):
        result_text = github_handlers.handle_file_contents(message)
        return {
            "agent_results": {"github": {"text": result_text}},
            "final_reply": result_text,
        }

    monkeypatch.setattr(app, "_invoke_graph", fake_invoke_graph)
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    event = _FakeEvent()
    app._process_and_reply(event, "user-789", "app.pyのファイル内容を見せて")

    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "reply"
    assert len(request.messages) >= 2
    assert all(len(m.text) <= 5000 for m in request.messages)
    assert "".join(m.text for m in request.messages) == long_file_content
