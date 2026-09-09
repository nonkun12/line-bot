from types import SimpleNamespace

import app
from internal_ask_route import register_internal_ask_route


def test_internal_ask_hides_internal_exception_details():
    flask_app = __import__("flask").Flask("security-test")
    register_internal_ask_route(
        flask_app,
        "secret-key",
        lambda user_id, message: (_ for _ in ()).throw(RuntimeError("private-detail")),
    )

    response = flask_app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "test"},
        headers={"x-internal-key": "secret-key"},
    )

    assert response.status_code == 500
    assert response.get_json() == {"ok": False, "error": "internal server error"}
    assert "private-detail" not in response.get_data(as_text=True)


def test_line_gateway_failure_sends_user_safe_error_reply(monkeypatch):
    replies = []

    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(
        app.app.ai_gateway,
        "handle",
        lambda request: (_ for _ in ()).throw(RuntimeError("gateway failed")),
    )
    monkeypatch.setattr(
        app,
        "_line_reply",
        lambda reply_token, text: replies.append((reply_token, text)),
    )
    monkeypatch.setattr(app, "_line_push", lambda user_id, text: None)

    event = SimpleNamespace(reply_token="reply-token")
    app._process_and_reply(event, "u1", "テスト")

    assert replies == [("reply-token", "一時的にエラーが発生しました。もう一度お試しください。")]


def test_line_gateway_failure_and_reply_failure_falls_back_to_push(monkeypatch):
    replies = []
    pushes = []

    monkeypatch.setattr(app, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(
        app.app.ai_gateway,
        "handle",
        lambda request: (_ for _ in ()).throw(RuntimeError("gateway failed")),
    )

    def fail_reply(reply_token, text):
        replies.append((reply_token, text))
        raise RuntimeError("line reply failed")

    monkeypatch.setattr(app, "_line_reply", fail_reply)
    monkeypatch.setattr(app, "_line_push", lambda user_id, text: pushes.append((user_id, text)))

    event = SimpleNamespace(reply_token="reply-token")
    app._process_and_reply(event, "u1", "テスト")

    assert replies == [("reply-token", "一時的にエラーが発生しました。もう一度お試しください。")]
    assert pushes == [("u1", "一時的にエラーが発生しました。もう一度お試しください。")]
