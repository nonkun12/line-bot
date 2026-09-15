from line_development import extract_development_instruction, dispatch_development_workflow
# LINE自動開発E2E


class FakeResponse:
    status_code = 204


class FakeWorkflowResponse:
    status_code = 200

    def json(self):
        return {"id": 123, "name": "LINE Development", "state": "active"}


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
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U999")
    reply = dispatch_development_workflow("英語学習機能を追加して", user_id="U123", token="secret")
    assert "権限がありません" in reply


def test_dispatch_uses_guarded_secretary_development_workflow(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        captured["timeout"] = kwargs["timeout"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "line_development.py にコメントを追加して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development-dispatch.yml" in captured["url"]
    assert captured["url"].endswith("/actions/workflows/line-development-dispatch.yml/dispatches")
    assert captured["json"] == {
        "ref": "main",
        "inputs": {"instruction": "line_development.py にコメントを追加して", "user_id": "U123"},
    }
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["timeout"] == 10.0
    assert "受け付けました" in reply


def test_dispatch_retries_transient_github_failure(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    calls = []

    class RetryResponse:
        status_code = 503
        text = "temporarily unavailable"
        headers = {}

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            return RetryResponse()
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    monkeypatch.setattr("line_development.time.sleep", lambda _: None)

    reply = dispatch_development_workflow(
        "line_development.py の本線E2Eテストを確認して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert len(calls) == 3
    assert "受け付けました" in reply


def test_dispatch_reports_auth_failure_without_retry(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    calls = []

    class AuthResponse:
        status_code = 401
        text = '{"message":"Bad credentials"}'
        headers = {}

    def fake_post(url, **kwargs):
        calls.append(1)
        return AuthResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "line_development.py の本線E2Eテストを確認して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert calls == [1]
    assert "HTTP 401" in reply
    assert "Token/権限" in reply


def test_worker_parse_plan_accepts_plain_json():
    from scripts.line_development_worker_v2 import parse_plan

    assert parse_plan('{"file": "tests/test_line_development.py"}') == {
        "file": "tests/test_line_development.py"
    }


def test_worker_parse_plan_accepts_fenced_json():
    from scripts.line_development_worker_v2 import parse_plan

    assert parse_plan(
        '```json\n{"file": "tests/test_line_development.py"}\n```'
    ) == {"file": "tests/test_line_development.py"}


def test_worker_parse_plan_accepts_json_with_explanation():
    from scripts.line_development_worker_v2 import parse_plan

    assert parse_plan(
        'Here is the plan:\n{"file": "tests/test_line_development.py"}\n'
    ) == {"file": "tests/test_line_development.py"}


def test_generic_development_request_routes_to_independent_app_builder(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_dispatch(requirement, *, user_id, token=None):
        captured["requirement"] = requirement
        captured["user_id"] = user_id
        captured["token"] = token
        return "APP_BUILDER_STARTED"

    monkeypatch.setattr("line_development.dispatch_app_development_workflow", fake_dispatch)
    reply = dispatch_development_workflow(
        "TODO管理Webアプリを作って",
        user_id="U123",
        token="secret",
    )

    assert reply == "APP_BUILDER_STARTED"
    assert captured == {
        "requirement": "TODO管理Webアプリを作って",
        "user_id": "U123",
        "token": "secret",
    }


def test_secretary_development_request_stays_on_line_bot(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "line_development.py にコメントを追加して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development-dispatch.yml" in captured["url"]
    assert "受け付けました" in reply
