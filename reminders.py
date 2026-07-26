import re
from datetime import datetime, timedelta, timezone


def handle_relative_time_reminder(message, user_id, call_mcp_tool, extract_quoted_text):
    """相対時間指定のリマインダーを生成する。"""
    relative_time_match = re.search(r"(\d+)(秒|分|時間)後", message)
    if not relative_time_match:
        return None

    amount = int(relative_time_match.group(1))
    unit = relative_time_match.group(2)

    jst = timezone(timedelta(hours=9))

    if unit == "秒":
        delta = timedelta(seconds=amount)
    elif unit == "分":
        delta = timedelta(minutes=amount)
    else:
        delta = timedelta(hours=amount)

    remind_at = (datetime.now(jst) + delta).isoformat()

    quoted = extract_quoted_text(message) if extract_quoted_text else None
    if quoted:
        reminder_text = quoted
    else:
        reminder_text = message[relative_time_match.end():]
        reminder_text = re.sub(r"^(に|、|,)+", "", reminder_text).strip()
        reminder_text = re.sub(
            r"(と言って|と教えて|教えて|知らせて|リマインドして|通知して|連絡して)$",
            "",
            reminder_text,
        ).strip()

    if not reminder_text:
        reminder_text = message

    return call_mcp_tool(
        "set_reminder",
        {
            "user_id": user_id,
            "remind_at": remind_at,
            "message": reminder_text,
            "repeat": "none",
        },
    )


def handle_daily_reminder(message, user_id, call_mcp_tool, now=None):
    """毎日/毎朝のリマインダーを生成する。"""
    if not (("毎日" in message or "毎朝" in message) and "時" in message):
        return None

    m = re.search(r"(?:毎日|毎朝)(\d+)時(.+)", message)
    if not m:
        return None

    hour = int(m.group(1))
    reminder_text = (
        m.group(2)
        .replace("を覚えて", "")
        .replace("覚えて", "")
        .replace("教えて", "")
        .replace("知らせて", "")
        .lstrip("に")
        .strip()
    )

    jst = timezone(timedelta(hours=9))
    current_now = now or datetime.now(jst)
    remind_at = current_now.replace(hour=hour, minute=0, second=0, microsecond=0)

    if remind_at <= current_now:
        remind_at += timedelta(days=1)

    return call_mcp_tool(
        "set_reminder",
        {
            "user_id": user_id,
            "remind_at": remind_at.isoformat(),
            "message": reminder_text,
            "repeat": "daily",
        },
    )


def handle_tomorrow_reminder(message, user_id, call_mcp_tool, now=None):
    """明日○時のリマインダーを生成する。"""
    if not ("明日" in message and "時" in message and ("覚えて" in message or "教えて" in message or "知らせて" in message)):
        return None

    m = re.search(r"明日(\d+)時(.+)", message)
    if not m:
        return None

    hour = int(m.group(1))
    reminder_text = (
        m.group(2)
        .replace("を覚えて", "")
        .replace("覚えて", "")
        .lstrip("に")
        .strip()
    )

    jst = timezone(timedelta(hours=9))
    current_now = now or datetime.now(jst)
    tomorrow = current_now + timedelta(days=1)
    remind_at = tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()

    return call_mcp_tool(
        "set_reminder",
        {
            "user_id": user_id,
            "remind_at": remind_at,
            "message": reminder_text,
            "repeat": "none",
        },
    )


def handle_list_reminders(user_id, call_mcp_tool):
    """登録済みリマインダー一覧を取得する。"""
    return call_mcp_tool("list_reminders", {"user_id": user_id})


def handle_cancel_reminder(user_id, arguments, call_mcp_tool, parse_mcp_json_list):
    """リマインダー削除を実行する。"""
    reminder_id = arguments.get("id")

    if not reminder_id:
        reminders = call_mcp_tool("list_reminders", {"user_id": user_id})
        reminder_list = parse_mcp_json_list(reminders)

        if reminder_list:
            reminder_id = reminder_list[-1].get("id")

    if not reminder_id:
        return "キャンセルできるリマインダーがありません。"

    return call_mcp_tool("cancel_reminder", {"user_id": user_id, "id": reminder_id})


def build_today_schedule_text(reminders, now=None):
    """今日の予定を自然な日本語テキストに整形する。"""
    if not reminders:
        return "今日の予定は特にありません。"

    jst = timezone(timedelta(hours=9))
    current_now = now or datetime.now(jst)
    today = current_now.date()

    todays_reminders = []
    for r in reminders:
        remind_at = r.get("remind_at")
        if not remind_at:
            continue
        try:
            if remind_at.endswith("Z"):
                dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(remind_at)
        except Exception:
            try:
                dt = datetime.strptime(remind_at, "%Y/%m/%d %H:%M:%S").replace(tzinfo=jst)
            except Exception:
                continue

        if dt.astimezone(jst).date() == today and dt.astimezone(jst) >= current_now:
            todays_reminders.append((dt.astimezone(jst), r.get("message", "")))

    if not todays_reminders:
        return "今日の予定は特にありません。"

    todays_reminders.sort(key=lambda item: item[0])
    lines = [f"・{dt.strftime('%H:%M')} {msg}" for dt, msg in todays_reminders]
    return "今日の予定は以下の通りです。\n" + "\n".join(lines)
