from datetime import datetime, timedelta, timezone

from reminders import (
    build_today_schedule_text,
    handle_cancel_reminder,
    handle_daily_reminder,
    handle_relative_time_reminder,
    handle_tomorrow_reminder,
)


def test_handle_relative_time_reminder_uses_quoted_text():
    calls = []

    def fake_call_mcp(name, arguments):
        calls.append((name, arguments))
        return "ok"

    result = handle_relative_time_reminder(
        "5分後に「会議」を教えて",
        "user-1",
        fake_call_mcp,
        lambda message: "会議",
    )

    assert result == "ok"
    assert calls[0][0] == "set_reminder"
    assert calls[0][1]["message"] == "会議"


def test_handle_daily_reminder_uses_daily_repeat():
    calls = []

    def fake_call_mcp(name, arguments):
        calls.append((name, arguments))
        return "ok"

    now = datetime(2026, 7, 26, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    result = handle_daily_reminder("毎日10時にお知らせ", "user-1", fake_call_mcp, now=now)

    assert result == "ok"
    assert calls[0][0] == "set_reminder"
    assert calls[0][1]["repeat"] == "daily"
    assert calls[0][1]["message"] == "お知らせ"


def test_handle_tomorrow_reminder_uses_tomorrow_time():
    calls = []

    def fake_call_mcp(name, arguments):
        calls.append((name, arguments))
        return "ok"

    now = datetime(2026, 7, 26, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    result = handle_tomorrow_reminder("明日12時に覚えて", "user-1", fake_call_mcp, now=now)

    assert result == "ok"
    assert calls[0][1]["repeat"] == "none"
    assert calls[0][1]["message"] == ""


def test_handle_cancel_reminder_uses_latest_id():
    calls = []

    def fake_call_mcp(name, arguments):
        calls.append((name, arguments))
        return "ok"

    def fake_parse(raw):
        return [{"id": 5}, {"id": 7}]

    result = handle_cancel_reminder("user-1", {}, fake_call_mcp, fake_parse)

    assert result == "ok"
    assert calls[0][0] == "list_reminders"
    assert calls[1][0] == "cancel_reminder"
    assert calls[1][1]["id"] == 7


def test_build_today_schedule_text_formats_schedule():
    now = datetime(2026, 7, 26, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    reminders = [
        {"remind_at": "2026-07-26T10:00:00+09:00", "message": "会議"},
        {"remind_at": "2026-07-27T10:00:00+09:00", "message": "明日の予定"},
    ]

    text = build_today_schedule_text(reminders, now=now)
    assert "会議" in text
    assert "明日の予定" not in text
    assert "今日の予定は以下の通りです。" in text
