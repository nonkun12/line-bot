import re
import unicodedata
from typing import Optional

from agents.notes.handlers import get_pending_note_action
from agents.notes.patterns import is_explicit_save_note


_LOOKUP_WORDS = [
    "ある", "あります", "残ってる", "残っています", "覚えてる", "覚えています",
    "覚えてるか", "覚えているか", "教えて", "確認して", "見せて", "探して", "検索して",
]


def is_note_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return False
    if re.match(r"^ID\s*\d+\s*(?:を)?(?:消して|消す|削除して|削除する|削除)$", text, re.IGNORECASE):
        return True
    if re.search(r"\d+番.*メモ.*削除", text):
        return True
    if is_explicit_save_note(text):
        return True
    if text.startswith("メモ"):
        return True
    if "メモ" in text and any(word in text for word in _LOOKUP_WORDS):
        return True
    # 「明日旅行する予定」のような予定の保存はNotes Agentへ送る。
    # 「予定ある？」「予定を確認して」などの照会は従来どおり除外する。
    if "予定" in text and not any(word in text for word in _LOOKUP_WORDS):
        return True
    if get_pending_note_action(user_id or ""):
        return True
    return False
