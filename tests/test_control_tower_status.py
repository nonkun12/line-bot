from core.control_tower_status import (
    build_control_tower_status_reply,
    is_control_tower_status_command,
)


def test_recognizes_explicit_status_commands_only():
    assert is_control_tower_status_command("統括AI 状況確認")
    assert is_control_tower_status_command("  分散Loop   状況確認 ")
    assert not is_control_tower_status_command("こんにちは")
    assert not is_control_tower_status_command("統括AIを強化して")


def test_reports_real_latest_run_and_keeps_status_read_only(monkeypatch):
    monkeypatch.setenv("AUTO_APPLY_PATCH", "false")
    monkeypatch.setenv("AUTO_DEPLOY", "false")

    def fake_get_json(url, *, token=""):
        assert "distributed-autonomous-loop.yml/runs" in url
        return {"workflow_runs": [{
            "status": "completed",
            "conclusion": "failure",
            "run_number": 42,
            "name": "Distributed Autonomous Development Loop",
            "created_at": "2026-10-16T00:00:00Z",
            "event": "workflow_dispatch",
            "head_sha": "1234567890abcdef",
            "html_url": "https://github.com/nonkun12/line-bot/actions/runs/42",
        }]}

    reply = build_control_tower_status_reply(
        "nonkun12/line-bot", "test-token", get_json=fake_get_json
    )
    assert "失敗または未合格（failure）" in reply
    assert "最新Run: #42" in reply
    assert "対象SHA: 1234567890ab" in reply
    assert "Task ID／キュー件数: Run概要からは未取得" in reply
    assert "Workflow成功だけではタスクPASSを意味しません" in reply
    assert "自動パッチ適用: 無効" in reply
    assert "自動デプロイ: 無効" in reply
    assert "マージ／デプロイは実行しません" in reply


def test_api_failure_is_not_reported_as_success():
    def fail(_url, *, token=""):
        raise RuntimeError("network down")

    reply = build_control_tower_status_reply("nonkun12/line-bot", get_json=fail)
    assert "取得できません" in reply
    assert "成功とは判定しません" in reply


def test_missing_repository_fails_closed():
    reply = build_control_tower_status_reply("")
    assert "状態取得不可" in reply
    assert "成功・正常とは判定しません" in reply
