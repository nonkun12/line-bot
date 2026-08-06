import re
from typing import Optional

from agents.notes.handlers import get_pending_note_action

_DELETE_ALL_NOTES_PATTERN = re.compile(
    r"メモ.*(全部|全て|すべて).*(消して|消す|削除|消していい)"
    r"|(全部|全て|すべて).*メモ.*(消して|消す|削除|消していい)"
    r"|^メモ(を)?消して$"
)

_AUTO_SAVE_NEGATIVE_PHRASES = [
    "ある？",
    "ありますか",
    "あるか",
    "あった？",
    "あったか",
    "確認",
    "教えて",
    "覚えて",
]


def is_note_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    text = (raw_message or "").strip()

    if not text:
        return False

    if text == "はい" and user_id is not None:
        return get_pending_note_action(user_id) is not None

    if text == "メモ一覧":
        return True

    if text.startswith("メモ検索"):
        return True

    if text.startswith("メモして"):
        return True

    if text.startswith("メモ削除"):
        return True

    if text in [
        "メモ削除全部",
        "メモ全て削除",
        "メモを全部削除",
        "メモ全部消して",
        "メモ全部削除",
        "全メモ削除",
        "メモを全削除",
    ]:
        return True

    if _DELETE_ALL_NOTES_PATTERN.search(text):
        return True

    if "メモ" in text and any(
        word in text for word in ["探して", "検索", "見せて", "私のメモ"]
    ):
        return True

    if re.search(r"\d+番.*メモ.*削除", text):
        return True

    if (
        ("予定" in text or "したい" in text or "忘れないように" in text)
        and len(text) > 5
        and not any(neg in text for neg in _AUTO_SAVE_NEGATIVE_PHRASES)
    ):
        return True

    return False
