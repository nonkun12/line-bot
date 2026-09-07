import re
import unicodedata
from typing import Optional

from agents.notes.handlers import get_pending_note_action


def is_note_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return False
    if re.match(r"^ID\s*\d+\s*(?:を)?(?:消して|消す|削除して|削除する|削除)$", text, re.IGNORECASE):
        return True
    if re.search(r"\d+番.*メモ.*削除", text):
        return True
    if text.startswith("メモ"):
        return True
    if get_pending_note_action(user_id or ""):
        return True
    return False
