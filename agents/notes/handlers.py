from __future__ import annotations

import re
import threading
import unicodedata
from typing import Any, Callable, Optional

CallMcpTool = Callable[[str, dict[str, Any]], Any]

_DELETE_ALL_NOTES_PATTERN = re.compile(
    r"メモ.*(全部|全て|すべて).*(消して|消す|削除|消していい)"
    r"|(全部|全て|すべて).*メモ.*(消して|消す|削除|消していい)"
    r"|^メモ(を)?消して$"
)

_pending_note_confirmations: dict[str, str] = {}
_pending_note_confirm_lock = threading.Lock()

_LOOKUP_QUESTION_RE = re.compile(
    r"(?:は|って|ある|あります|残ってる|残っています|覚えてる|覚えています|教えて|確認して|見せて|探して|検索して)[？?]?$"
)


def _extract_search_keyword(message: str) -> str:
    return re.sub(r"^メモ検索\s*[:：]?\s*", "", message)


def _normalize_natural_search_message(message: str) -> str:
    # 「メモはある？」「私のメモは？」「メモを見せて」などは全件検索。
    if any(phrase in message for phrase in ["私のメモ", "メモはある", "メモある", "メモはあります", "メモあります"]):
        return ""
    exact_phrases = ["LINE Botのメモを探して", "メモを探して", "予定はある？", "予定はある?", "予定がありますか"]
    if message in exact_phrases:
        return "予定" if message.startswith("予定") else ""

    # 予定・予約の確認は、その対象語だけを検索キーワードにする。
    if "予定" in message or "予約" in message:
        keyword = message
        for phrase in ["予定はある？", "予定はある?", "予定はありますか", "予定がある？", "予定がある?", "予定があります", "覚えてる？", "覚えてる?", "覚えていますか", "ありますか？", "ありますか?", "ある？", "ある?"]:
            keyword = keyword.replace(phrase, "")
        keyword = keyword.replace("私の", "").replace("覚えてる", "").replace("覚えています", "").replace("確認して", "").strip()
        return keyword or "予定"

    suffixes = [
        "LINE Botのメモを探して", "メモを探して", "メモを見せて", "メモを検索して",
        "を検索して", "を探して", "を見せて",
    ]
    for suffix in suffixes:
        if message.endswith(suffix) and message != suffix:
            return message[: -len(suffix)].strip()
    return (
        message.replace("LINE Botのメモを探して", "")
        .replace("メモを探して", "").replace("メモを見せて", "")
        .replace("メモを検索して", "").replace("メモ", "")
        .replace("を見せて", "").replace("を検索して", "")
        .replace("検索", "").replace("探して", "").replace("見せて", "").strip()
    )


def _classify_note_category(body: str) -> str:
    lower_body = body.lower()
    if any(k in lower_body for k in ["python", "program", "プログラム", "ai", "コード"]):
        return "技術"
    if any(k in body for k in ["勉強", "英語", "資格", "学習"]):
        return "学習"
    if any(k in body for k in ["予定", "予約", "会議", "行く"]):
        return "予定"
    if any(k in body for k in ["買う", "購入", "買い物"]):
        return "生活"
    return "一般"


def _should_auto_save(message: str) -> bool:
    if not ("予定" in message or "したい" in message or "忘れないように" in message):
        return False
    if len(message) <= 5:
        return False
    for phrase in ["ある？", "ありますか", "あるか", "あった？", "あったか", "確認", "教えて", "覚えて"]:
        if phrase in message:
            return False
    if _LOOKUP_QUESTION_RE.search(message):
        return False
    return True


def handle_list_notes(user_id: str, call_mcp_tool: CallMcpTool) -> Any:
    return call_mcp_tool("search_notes", {"user_id": user_id, "keyword": ""})


def handle_search_notes(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Any:
    keyword = _extract_search_keyword(message)
    if not keyword:
        return "検索キーワードを指定してください。\n例: メモ検索 テニス"
    return call_mcp_tool("search_notes", {"user_id": user_id, "keyword": keyword})


def handle_natural_note_search(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Any:
    keyword = _normalize_natural_search_message(message)
    return call_mcp_tool("search_notes", {"user_id": user_id, "keyword": keyword})


def handle_save_note(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Any:
    body = re.sub(r"^メモして\s*[:：]?\s*", "", message)
    category = _classify_note_category(body)
    return call_mcp_tool("save_note", {"user_id": user_id, "title": "LINEメモ", "body": body, "category": category})


def handle_auto_save_note(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Optional[Any]:
    if not _should_auto_save(message):
        return None
    return call_mcp_tool("save_note", {"user_id": user_id, "title": "自動メモ", "body": message, "category": "一般"})


def handle_delete_note(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Optional[Any]:
    """Delete a note by natural language or explicit note ID."""
    message = unicodedata.normalize("NFKC", (message or "").strip())
    id_match = re.match(r"^ID\s*(\d+)\s*(?:を)?(?:消して|消す|削除して|削除する|削除)$", message, re.IGNORECASE)
    if id_match:
        return call_mcp_tool("delete_note", {"user_id": user_id, "id": id_match.group(1)})

    natural_match = re.search(r"(\d+)番.*メモ.*削除", message)
    if natural_match:
        return call_mcp_tool("delete_note", {"user_id": user_id, "id": natural_match.group(1)})

    if message.startswith("メモ削除"):
        note_id = unicodedata.normalize("NFKC", message.replace("メモ削除", "").strip())
        if not note_id:
            return "削除するメモIDを指定してください。\n例: メモ削除25"
        print("DELETE DEBUG user_id=", user_id, "note_id=", note_id)
        return call_mcp_tool("delete_note", {"user_id": user_id, "id": note_id})
    return None


def _is_delete_all_notes_message(message: str) -> bool:
    return _DELETE_ALL_NOTES_PATTERN.search(message) is not None


def get_pending_note_action(user_id: str) -> Optional[str]:
    with _pending_note_confirm_lock:
        return _pending_note_confirmations.get(user_id)


def _set_pending_note_action(user_id: str, action: str) -> None:
    with _pending_note_confirm_lock:
        _pending_note_confirmations[user_id] = action


def _pop_pending_note_action(user_id: str) -> Optional[str]:
    with _pending_note_confirm_lock:
        return _pending_note_confirmations.pop(user_id, None)


def handle_note_message(message: str, user_id: str, call_mcp_tool: CallMcpTool) -> Optional[Any]:
    """Handle note-related messages through the shared Notes handler layer."""
    message = unicodedata.normalize("NFKC", (message or "").strip())
    if message == "メモ一覧":
        return handle_list_notes(user_id, call_mcp_tool)
    if message.startswith("メモ検索"):
        return handle_search_notes(message, user_id, call_mcp_tool)
    if message.startswith("メモして"):
        return handle_save_note(message, user_id, call_mcp_tool)
    if _is_delete_all_notes_message(message):
        _set_pending_note_action(user_id, "delete_all_notes")
        return "全メモを削除しますか？「はい」と送ってください"
    if message == "はい":
        action = _pop_pending_note_action(user_id)
        if action == "delete_all_notes":
            return call_mcp_tool("delete_all_notes", {"user_id": user_id})
        return None
    delete_result = handle_delete_note(message, user_id, call_mcp_tool)
    if delete_result is not None:
        return delete_result
    if ("メモ" in message or "予定" in message or "予約" in message) and any(keyword in message for keyword in ["探して", "検索", "見せて", "私のメモ", "ある", "あります", "残って", "覚えて", "確認"]):
        return handle_natural_note_search(message, user_id, call_mcp_tool)
    auto_save_result = handle_auto_save_note(message, user_id, call_mcp_tool)
    if auto_save_result is not None:
        return auto_save_result
    return None
