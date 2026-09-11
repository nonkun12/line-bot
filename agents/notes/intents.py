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

    # 予定・将来行動の自然文は、質問でなければ保存意図として扱う。
    if "予定" in text:
        has_lookup = any(word in text for word in _LOOKUP_WORDS) or text.endswith("？") or text.endswith("?")
        if not has_lookup:
            return True

    # 「明日電話したい」のような明示的な将来行動も自然メモとして扱う。
    future_markers = ("明日", "あした", "来週", "今度")
    action_markers = ("したい", "する", "行く", "行きたい", "電話")
    if any(marker in text for marker in future_markers):
        has_lookup = any(word in text for word in _LOOKUP_WORDS) or text.endswith("？") or text.endswith("?")
        if not has_lookup and any(marker in text for marker in action_markers):
            return True

    if "メモ" in text and any(word in text for word in _LOOKUP_WORDS):
        return True
    if get_pending_note_action(user_id or ""):
        return True
    return False
