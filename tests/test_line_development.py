from line_development import extract_development_instruction, dispatch_development_workflow


class FakeResponse:
    status_code = 204


def test_normal_message_is_not_development():
    assert extract_development_instruction("明日の予定を教えて") is None
    assert extract_development_instruction("github repo") is None


def test_explicit_japanese_development_command():
    assert extract_development_instruction("開発: 天気機能を改善して") == "天気機能を改善して"


def test_explicit_english_development_command():
    assert extract_development_instruction("dev: add a health check test") == "add a health check test"


def test_empty_development_command_is_rejected():
    assert extract_development_instruction("開発:") == ""
    assert extract_development_instruction("dev:   ") == ""
    assert "空です" in dispatch_development_workflow("", user_id="u1", token="test")


def test_unauthorized_user_is_rejected(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U_ALLOWED")
    assert "権限がありません" in dispatch_development_workflow(
        "英語学習機能を追加して", user_id="U_OTHER", token="secret"
    )


def test_authorized_dispatch_uses_workflow_dispatch(monkeypatch):
    captured = {}
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "英語学習機能を追加して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development.yml/dispatches" in captured["url"]
    assert captured["json"] == {
        "ref": "main",
        "inputs": {"instruction": "英語学習機能を追加して", "user_id": "U123"},
    }
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert "受け付けました" in reply
