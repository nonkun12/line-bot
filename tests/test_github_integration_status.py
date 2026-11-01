from core.github_integration_status import (
    build_github_integration_status_reply,
    is_github_integration_status_request,
)


def test_detects_japanese_github_integration_status_questions():
    assert is_github_integration_status_request("GitHub連携の有無を教えて")
    assert is_github_integration_status_request("GitHubとの接続状況を確認して")
    assert is_github_integration_status_request("GitHub連携設定は有効ですか？")


def test_does_not_capture_unrelated_github_requests():
    assert not is_github_integration_status_request("GitHubの最新PRを見せて")
    assert not is_github_integration_status_request("GitHubでPythonを検索して")
    assert not is_github_integration_status_request("このアプリを改善して")


def test_reports_configured_prerequisites_without_claiming_live_connectivity(tmp_path):
    workflow = tmp_path / "line-development-dispatch.yml"
    workflow.write_text("name: LINE Development Dispatch\n", encoding="utf-8")

    reply = build_github_integration_status_reply(
        token="configured-secret",
        allowed_user_ids="U123,U456",
        workflow_path=workflow,
    )

    assert "GITHUB_TOKEN: 設定あり" in reply
    assert "DEV_ALLOWED_USER_IDS: 設定あり" in reply
    assert "リポジトリ内に存在" in reply
    assert "必要な設定項目は揃っています" in reply
    assert "実疎通は、この読み取り確認では未検証" in reply
    assert "configured-secret" not in reply
    assert "U123" not in reply


def test_reports_missing_prerequisites(tmp_path):
    reply = build_github_integration_status_reply(
        token="",
        allowed_user_ids="",
        workflow_path=tmp_path / "missing.yml",
    )

    assert "GITHUB_TOKEN: 未設定" in reply
    assert "DEV_ALLOWED_USER_IDS: 未設定" in reply
    assert "見つかりません" in reply
    assert "不足している設定があります" in reply
