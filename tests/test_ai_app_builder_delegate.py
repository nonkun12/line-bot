import json

from n8n_delegate import is_ai_app_builder_request, _delegate_to_ai_app_builder, _delegate_to_n8n


def test_app_builder_intent_matches_explicit_requests():
    assert is_ai_app_builder_request("Todoアプリを作って")
    assert is_ai_app_builder_request("簡単なWebアプリを作成して")
    assert not is_ai_app_builder_request("今日の予定は？")
    assert not is_ai_app_builder_request("")


def test_n8n_path_remains_for_non_app_requests(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("n8n_delegate.httpx.post", fake_post)
    monkeypatch.setattr("n8n_delegate.record_step", lambda *args, **kwargs: None)

    _delegate_to_n8n("U1", "今日の予定は？", "https://n8n.example/webhook")

    assert seen["url"] == "https://n8n.example/webhook"
    assert seen["kwargs"]["json"] == {"user_id": "U1", "message": "今日の予定は？"}


def test_ai_app_builder_success_pushes_summary(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "status": "success",
                "project_path": "/home/test/AI-Projects/todo-app",
                "summary": "アプリを作成しました。",
            }

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("n8n_delegate.httpx.post", fake_post)
    monkeypatch.setattr("n8n_delegate.AI_APP_BUILDER_URL", "https://builder.example")
    monkeypatch.setattr("n8n_delegate.AI_APP_BUILDER_SHARED_SECRET", "secret")
    monkeypatch.setattr("n8n_delegate.record_step", lambda *args, **kwargs: None)
    monkeypatch.setattr("n8n_delegate._push_line_reply", lambda user_id, text: seen.update(push=(user_id, text)))

    assert _delegate_to_ai_app_builder("U1", "Todoアプリを作って") is True
    assert seen["url"] == "https://builder.example/interface/generate"
    assert seen["kwargs"]["headers"]["x-shared-secret"] == "secret"
    assert seen["push"] == (
        "U1",
        "アプリを作成しました。\n\n作成先: /home/test/AI-Projects/todo-app",
    )


def test_ai_app_builder_http_error_does_not_fall_through_to_n8n(monkeypatch):
    seen = []

    class FakeResponse:
        status_code = 500

        def json(self):
            return {"error": "boom"}

    def fake_post(url, **kwargs):
        seen.append(url)
        return FakeResponse()

    monkeypatch.setattr("n8n_delegate.httpx.post", fake_post)
    monkeypatch.setattr("n8n_delegate.AI_APP_BUILDER_URL", "https://builder.example")
    monkeypatch.setattr("n8n_delegate.AI_APP_BUILDER_SHARED_SECRET", "")
    monkeypatch.setattr("n8n_delegate.record_step", lambda *args, **kwargs: None)
    monkeypatch.setattr("n8n_delegate._push_line_reply", lambda *args, **kwargs: None)

    _delegate_to_n8n("U1", "Todoアプリを作って", "https://n8n.example/webhook")

    assert seen == ["https://builder.example/interface/generate"]


def test_ai_app_builder_without_url_leaves_existing_path_untouched(monkeypatch):
    called = []
    monkeypatch.setattr("n8n_delegate.AI_APP_BUILDER_URL", "")
    monkeypatch.setattr("n8n_delegate._delegate_to_ai_app_builder", lambda *args: called.append(args) or False)
    monkeypatch.setattr("n8n_delegate.httpx.post", lambda url, **kwargs: type("R", (), {"status_code": 200})())
    monkeypatch.setattr("n8n_delegate.record_step", lambda *args, **kwargs: None)

    _delegate_to_n8n("U1", "Todoアプリを作って", "https://n8n.example/webhook")

    assert called == [("U1", "Todoアプリを作って")]
