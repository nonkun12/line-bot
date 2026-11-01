from app_development import extract_app_development_request


def test_explicit_and_natural_japanese_creation_requests_are_supported():
    assert extract_app_development_request("アプリ開発: 家計簿アプリを作って") == "家計簿アプリを作って"
    assert extract_app_development_request("アプリを作って") == "アプリを作って"


def test_empty_explicit_request_is_preserved():
    assert extract_app_development_request("アプリ開発:") == ""


def test_english_prefix_is_supported():
    assert extract_app_development_request("app-dev: build a tiny todo web app") == "build a tiny todo web app"


import pytest

from app_development import dispatch_app_development_workflow


@pytest.mark.parametrize(
    "message",
    [
        "アプリを作って。ただしコード変更・PR作成・マージ・デプロイは行わないでください。結果だけ報告してください。",
        "app-dev: 家計簿アプリを作って。読み取り専用で確認してください。",
        "アプリを作ってください。GitHub Actions起動はしないでください。",
        "アプリの受付結果だけ報告してください。変更は行わず。",
    ],
)
def test_read_only_constraints_override_app_creation_intent(message):
    assert extract_app_development_request(message) is None


def test_dispatch_rejects_read_only_instruction_before_github_call(monkeypatch):
    def unexpected_post(*args, **kwargs):
        pytest.fail("GitHub Actions must not be called for a read-only request")

    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123")
    monkeypatch.setattr("app_development.httpx.post", unexpected_post)
    reply = dispatch_app_development_workflow(
        "アプリを作って。ただし変更・PR作成・マージ・デプロイは行わないでください。",
        user_id="U123",
        token="test-token",
    )
    assert "起動していません" in reply
