import pytest

from line_development import extract_development_instruction, dispatch_development_workflow


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


@pytest.mark.parametrize(
    "message",
    [
        "このアプリを改善して",
        "LINE AI Secretaryの通知機能を追加して",
        "line-botのコードを修正してください",
        "このシステムのテストを実行して",
    ],
)
def test_clear_natural_language_development_commands_are_dispatched(message):
    assert extract_development_instruction(message) == message


@pytest.mark.parametrize(
    "message",
    [
        "このアプリの改善方法を教えて",
        "システムをどうやって開発できますか",
        "アプリのおすすめを比較して",
        "明日の予定を教えて",
        "今日は何を追加したらよい？",
    ],
)
def test_questions_and_non_commands_stay_in_normal_chat(message):
    assert extract_development_instruction(message) is None


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


def test_new_app_request_uses_governed_development_workflow(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "TODO管理Webアプリを作って",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development-dispatch.yml/dispatches" in captured["url"]
    assert captured["json"]["inputs"]["instruction"] == "TODO管理Webアプリを作って"
    assert "受け付けました" in reply


@pytest.mark.parametrize(
    "instruction",
    [
        "新しいアプリを開発して",
        "アプリ作成して",
        "新規システムを構築して",
        "create a new app",
        "build a new web app",
    ],
)
def test_new_app_creation_variants_are_dispatched_to_governed_workflow(monkeypatch, instruction):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        instruction,
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert captured["url"].endswith("/actions/workflows/line-development-dispatch.yml/dispatches")
    assert captured["json"]["inputs"]["instruction"] == instruction
    assert "受け付けました" in reply


def test_generic_existing_feature_request_uses_line_development_workflow(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "天気機能を改善して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development-dispatch.yml" in captured["url"]
    assert captured["json"]["inputs"]["instruction"] == "天気機能を改善して"
    assert "受け付けました" in reply


def test_existing_app_feature_improvement_is_not_blocked(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("line_development.httpx.post", fake_post)
    reply = dispatch_development_workflow(
        "既存アプリの通知機能を改善して",
        user_id="U123",
        token="secret",
        repository="nonkun12/line-bot",
    )

    assert "/actions/workflows/line-development-dispatch.yml" in captured["url"]
    assert captured["json"]["inputs"]["instruction"] == "既存アプリの通知機能を改善して"
    assert "受け付けました" in reply


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



def test_generic_classifier_semantics_are_preserved_outside_line_dispatch():
    from core.task_routing import TaskClassifier, TaskMode

    # The shared classifier remains responsible for independent software requests.
    assert TaskClassifier().classify(
        "開発: TODO管理Webアプリを作って"
    ).mode == TaskMode.NEW_SOFTWARE



def test_read_only_receipt_and_actions_status_request_is_not_dispatched():
    message = (
        "line-botの開発指示受付が正常に動作するかテストしてください。"
        "コード変更・PR作成・マージ・デプロイは行わず、"
        "受付結果とGitHub Actionsへの連携状況だけ報告してください。"
    )
    assert extract_development_instruction(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "line-botの受付結果だけ報告してください。コード変更は行わず。",
        "読み取り専用でこのシステムのテスト状況を調査して",
        "このアプリを変更せずに結果だけ確認して",
    ],
)
def test_non_mutating_diagnostic_requests_are_not_dispatched(message):
    assert extract_development_instruction(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "開発: 読み取り専用でline-botのテスト状況を調査して",
        "dev: line-botの受付結果だけ確認して。コード変更は行わず",
        "開発: line-botのコード変更・PR作成・マージ・デプロイは行わず、結果だけ報告して",
    ],
)
def test_explicit_dev_prefix_cannot_override_non_execution_constraints(message):
    assert extract_development_instruction(message) is None



def test_exact_line_connectivity_smoke_message_never_dispatches_development():
    message = (
        "疎通テストです。LINEからのメッセージ受信と返信が正常に動作するか確認してください。"
        "GitHubの検索・Actions起動・コード変更・PR作成・マージ・デプロイは一切行わないでください。"
        "「LINE受信成功」「返信成功」「GitHub連携の有無」だけ報告してください。"
    )
    assert extract_development_instruction(message) is None



def test_exact_line_connectivity_read_only_message_is_not_dispatched():
    message = (
        "疎通テストです。LINEからのメッセージ受信と返信が正常に動作するか確認してください。"
        "GitHubの検索・Actions起動・コード変更・PR作成・マージ・デプロイは一切行わないでください。"
        "「LINE受信成功」「返信成功」「GitHub連携の有無」だけ報告してください。"
    )
    assert extract_development_instruction(message) is None



def test_shared_read_only_guard_blocks_app_style_constraints_too():
    from core.request_safety import is_non_execution_request

    assert is_non_execution_request(
        "アプリを作って。ただしコード変更・PR作成・マージ・デプロイは行わないでください。"
    )
    assert extract_development_instruction(
        "line-botのコードを改善して。ただしGitHub Actions起動はしないでください。"
    ) is None
