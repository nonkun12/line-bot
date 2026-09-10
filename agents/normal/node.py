"""
Normal Agent LangGraph Node
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import mcp_client
from graph.state import AgentState
from agents.normal.handlers import handle_normal_message
from gemini_n8n_client import GeminiN8nError, call_gemini_via_n8n

_LOOKUP_QUESTION_RE = re.compile(
    r"(?:予定|メモ|用事|スケジュール).*(?:は|って|ある|あります|残ってる|残っています|教えて|確認して|見せて)[？?]?$"
)
_REMINDER_LOOKUP_RE = re.compile(
    r"^(?:今)?(?:予定|用事|スケジュール)(?:が|は)?(?:ある|あります|残ってる|残っています)(?:の|か)?[？?]?$"
)
_CANCEL_REMINDER_RE = re.compile(
    r"(?:リマインダー|予定|スケジュール).*(?:キャンセル|取り消|取消|消して|削除)"
)
_WORK_STATUS_MESSAGES = {"作業確認", "作業状況確認", "作業状況を確認", "進捗確認", "進捗を確認"}


def _call_mcp_tool(state: AgentState):
    call_mcp_tool = state.get("call_mcp_tool")
    if callable(call_mcp_tool):
        return call_mcp_tool
    return mcp_client.call_mcp_tool


def _is_reminder_lookup_question(message: str) -> bool:
    return bool(_REMINDER_LOOKUP_RE.fullmatch((message or "").strip()))


def _is_reminder_cancel_request(message: str) -> bool:
    return bool(_CANCEL_REMINDER_RE.search((message or "").strip()))


def _is_note_lookup_question(message: str) -> bool:
    text = (message or "").strip()
    if not text or text.startswith("メモ：") or text.startswith("メモ:"):
        return False
    return bool(_LOOKUP_QUESTION_RE.search(text))


def _extract_note_lookup_keyword(message: str) -> str:
    text = re.sub(r"[？?]+$", "", (message or "").strip()).strip()
    generic_queries = [
        "さっきのメモは", "さっきのメモって", "さっきの予定は", "さっきの予定って",
        "メモを教えて", "メモを確認して", "メモを見せて", "予定を教えて",
        "予定を確認して", "予定を見せて", "明日の予定は", "今日の予定は",
    ]
    if text in generic_queries:
        if text.startswith("明日の"):
            return "明日"
        if text.startswith("今日の"):
            return "今日"
        return ""
    text = re.sub(
        r"(?:の)?(?:予定|用事|スケジュール)(?:は|って|ある|あります|残ってる|残っています|教えて|確認して|見せて)?$",
        "", text,
    )
    return text.strip()


def _format_note_lookup_result(result):
    if result is None:
        return "メモは見つかりませんでした。"
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        data = result
    if isinstance(data, list):
        if not data:
            return "メモは見つかりませんでした。"
        lines = []
        for item in data[:10]:
            if isinstance(item, dict):
                title = item.get("title") or "メモ"
                body = item.get("body") or item.get("content") or ""
                lines.append(f"- {title}: {body}" if body and body != title else f"- {title}")
            else:
                lines.append(f"- {item}")
        return "保存されているメモは次の通りです。\n" + "\n".join(lines)
    if isinstance(data, dict):
        title = data.get("title") or "メモ"
        body = data.get("body") or data.get("content") or ""
        return f"保存されているメモがあります。\n- {title}: {body}" if body else f"保存されているメモがあります。\n- {title}"
    text = str(data).strip()
    return text if text else "メモは見つかりませんでした。"


def _normal_provider() -> str:
    provider = os.getenv("NORMAL_AGENT_PROVIDER", "groq").strip().lower()
    return provider if provider in {"groq", "gemini"} else "groq"


def _gemini_request_id(state: AgentState) -> str:
    request_id = state.get("request_id")
    return str(request_id) if request_id else uuid.uuid4().hex


def _run_normal_generation(state: AgentState, raw_message: str, user_id: str, call_mcp_tool):
    provider = _normal_provider()
    if provider != "gemini":
        return handle_normal_message(raw_message, user_id, call_mcp_tool), "groq"
    try:
        data = call_gemini_via_n8n(
            message=raw_message, user_id=user_id,
            request_id=_gemini_request_id(state), timeout=10.0,
        )
        return data["reply"].strip(), "gemini"
    except GeminiN8nError as exc:
        print("[GEMINI FALLBACK] n8n Gemini failed:", exc)
        return handle_normal_message(raw_message, user_id, call_mcp_tool), "groq_fallback"


def _extract_cancel_target(message: str):
    """キャンセル依頼から指定日時を抽出する。現在は明日/今日の時刻指定を優先対応。"""
    text = (message or "").strip()
    day_offset = None
    if "明日" in text:
        day_offset = 1
    elif "今日" in text:
        day_offset = 0
    if day_offset is None:
        return None

    match = re.search(r"(?:今日|明日)の?\s*(\d{1,2})時(?:\s*(\d{1,2})分)?", text)
    if not match:
        match = re.search(r"(?:今日|明日)\s*(\d{1,2})時(?:\s*(\d{1,2})分)?", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None

    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    return (now + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _find_reminder_id_by_datetime(reminders, target):
    """一覧から指定日時(JST)に一致するリマインダーidを取得する。"""
    if target is None:
        return None
    if isinstance(reminders, str):
        try:
            parsed = json.loads(reminders)
            if isinstance(parsed, list):
                reminders = parsed
        except Exception:
            pass
    if isinstance(reminders, list):
        for item in reminders:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            raw = item.get("remind_at")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
                dt = dt.astimezone(ZoneInfo("Asia/Tokyo"))
                if dt.replace(second=0, microsecond=0) == target:
                    return int(item["id"])
            except (ValueError, TypeError):
                continue
        return None
    for line in str(reminders or "").splitlines():
        id_match = re.search(r"\bid\s*[=:]\s*(\d+)", line, re.IGNORECASE)
        date_match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})(?::\d{2})?", line)
        if not id_match or not date_match:
            continue
        y, mo, d, h, mi = map(int, date_match.groups())
        if (y, mo, d, h, mi) == (target.year, target.month, target.day, target.hour, target.minute):
            return int(id_match.group(1))
    return None


def normal_agent_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = _call_mcp_tool(state)

    if raw_message.strip() in _WORK_STATUS_MESSAGES:
        try:
            from app import generate_ai_secretary_report
            result_text = generate_ai_secretary_report(user_id)
            provider = "ai_secretary_report"
        except Exception as e:
            print("[WORK STATUS] AI secretary report error:", e)
            result_text = "作業確認の取得中にエラーが発生しました。もう一度お試しください。"
            provider = "ai_secretary_report_error"
    elif _is_reminder_cancel_request(raw_message):
        target_time = _extract_cancel_target(raw_message)
        print("[REMINDER CANCEL GUARD] cancellation request:", raw_message, "target:", target_time)
        try:
            if target_time is None:
                result_text = "削除する予定の日時を指定してください。例：『明日の10時の予定を削除して』"
            else:
                reminders = call_mcp_tool("list_reminders", {"user_id": user_id})
                target_id = _find_reminder_id_by_datetime(reminders, target_time)
                if not target_id:
                    result_text = "指定した日時のリマインダーが見つかりませんでした。"
                else:
                    print("[REMINDER CANCEL GUARD] target id:", target_id)
                    result_text = call_mcp_tool(
                        "cancel_reminder",
                        {"user_id": user_id, "id": int(target_id)},
                    )
            provider = "mcp"
        except Exception as e:
            print("[REMINDER CANCEL GUARD] error:", e)
            result_text = "リマインダーのキャンセル中にエラーが発生しました。もう一度お試しください。"
            provider = "mcp_error"
    elif _is_reminder_lookup_question(raw_message):
        try:
            result_text = call_mcp_tool("list_reminders", {"user_id": user_id})
            if result_text is None or not str(result_text).strip():
                result_text = "予定はありません。"
        except Exception as e:
            print("[REMINDER LOOKUP GUARD] list_reminders error:", e)
            result_text = "予定の確認中にエラーが発生しました。もう一度お試しください。"
        provider = "mcp"
    elif _is_note_lookup_question(raw_message):
        try:
            result_text = call_mcp_tool("search_notes", {"user_id": user_id, "keyword": _extract_note_lookup_keyword(raw_message)})
            result_text = _format_note_lookup_result(result_text)
        except Exception as e:
            print("[NOTE LOOKUP GUARD] search_notes error:", e)
            result_text = "メモの検索中にエラーが発生しました。もう一度お試しください。"
        provider = "mcp"
    else:
        result_text, provider = _run_normal_generation(state, raw_message, user_id, call_mcp_tool)

    agent_results = dict(state.get("agent_results", {}))
    agent_results["normal"] = {"text": result_text, "provider": provider}
    return {**state, "agent_results": agent_results}
