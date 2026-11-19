from datetime import datetime
from zoneinfo import ZoneInfo

from agents.normal.node import (
    _extract_cancel_target,
    _find_reminder_id_by_datetime,
    normal_agent_node,
)


JST = ZoneInfo("Asia/Tokyo")


def test_cancel_without_datetime_never_calls_mcp():
    calls = []

    def call_mcp_tool(*args):
        calls.append(args)
        raise AssertionError("MCP must not be called without an explicit datetime")

    result = normal_agent_node(
        {
            "user_id": "test-user",
            "raw_message": "予定を削除して",
            "agent_results": {},
            "call_mcp_tool": call_mcp_tool,
        }
    )

    assert calls == []
    assert "日時を指定してください" in result["agent_results"]["normal"]["text"]
    assert result["agent_results"]["normal"]["provider"] == "mcp"


def test_find_reminder_id_requires_exact_jst_minute():
    target = datetime(2026, 9, 11, 10, 0, tzinfo=JST)
    reminders = [
        {"id": 10, "remind_at": "2026-09-11T09:59:00+09:00"},
        {"id": 20, "remind_at": "2026-09-11T10:00:00+09:00"},
        {"id": 30, "remind_at": "2026-09-11T10:01:00+09:00"},
    ]

    assert _find_reminder_id_by_datetime(reminders, target) == 20
    assert _find_reminder_id_by_datetime(reminders, target.replace(minute=30)) is None


def test_cancel_datetime_parser_rejects_invalid_time_and_accepts_minute():
    assert _extract_cancel_target("明日の25時の予定を削除して") is None
    assert _extract_cancel_target("今日の10時30分の予定を削除して") is not None
