import re
import unicodedata
from typing import Optional

from agents.notes.handlers import get_pending_note_action
from agents.notes.patterns import is_explicit_save_note


_LOOKUP_WORDS = [
    "ある", "あります", "残ってる", "残っています", "覚えてる", "覚えています",
    "覚えてるか", "覚えているか", "教えて", "確認して", "見せて", "探して", "検索して",
]
_SCHEDULE_LOOKUP_RE = re.compile(
    r"予定.*(?:は\s*[?？]|ありますか|ある[?？]?$|教えて|確認して|見せて|残って)"
)
_FUTURE_ACTION_RE = re.compile(
    r"(?:今日|明日|今週|来週).*(?:したい|やりたい|する|行く|電話|会う|予約|予定)"
)


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

    # 予定の照会はNotesの自動保存対象にしない。
    if _SCHEDULE_LOOKUP_RE.search(text) or (
        "予定" in text and any(word in text for word in _LOOKUP_WORDS)
    ):
        return False

    if "メモ" in text and any(word in text for word in _LOOKUP_WORDS):
        return True
    if "予定" in text and not any(word in text for word in _LOOKUP_WORDS):
        return True
    if _FUTURE_ACTION_RE.search(text):
        return True

    if get_pending_note_action(user_id or ""):
        return True
    return False
