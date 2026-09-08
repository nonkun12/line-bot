import re
import unicodedata
from typing import Optional

from agents.notes.handlers import get_pending_note_action


_LOOKUP_WORDS = [
    "ある", "あります", "残ってる", "残っています", "覚えてる", "覚えています",
    "覚えてるか", "覚えているか", "教えて", "確認して", "見せて", "探して", "検索して",
]

# 「テストをメモして」「明日の10時にテストするとメモして」のように、
# 文末の「メモして」が明示されている場合は、リマインダーではなく
# Notes Agentへ確実にルーティングする。
_EXPLICIT_SAVE_NOTE_RE = re.compile(r".+(?:を)?メモして[。！!？?]?$")
_SAVE_NOTE_TO_RE = re.compile(r"^メモに\s*.+保存して[。！!？?]?$")


def is_note_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return False
    if re.match(r"^ID\s*\d+\s*(?:を)?(?:消して|消す|削除して|削除する|削除)$", text, re.IGNORECASE):
        return True
    if re.search(r"\d+番.*メモ.*削除", text):
        return True
    # 明示的なメモ保存は最優先。これをNormal/Reminder側へ流さない。
    if _EXPLICIT_SAVE_NOTE_RE.match(text) or _SAVE_NOTE_TO_RE.match(text):
        return True
    if text.startswith("メモ"):
        return True
    # 「予定ある？」「予定確認して」などはリマインダー/予定確認であり、
    # Notes Agentへ誤ルーティングしない。メモ検索だけをNotesへ振り分ける。
    if "メモ" in text and any(word in text for word in _LOOKUP_WORDS):
        return True
    if get_pending_note_action(user_id or ""):
        return True
    return False
