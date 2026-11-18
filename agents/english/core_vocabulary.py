"""Bounded Side 5 worker for reviewed English core-vocabulary learning.

Reuses the existing local lexicon, per-user rotation, and quiz persistence.
No network calls, paid providers, dictionary synthesis, or shared anonymous state.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.english.core_image import _ENTRIES
from agents.english.quiz import grade_quiz, start_quiz
from agents.english.quiz_state import select_daily_words

SIDE_ID = "side_5_english_core_vocabulary"
TARGET_WORDS = 1000
_MAX_USER_ID_CHARS = 200


@dataclass(frozen=True)
class CoreVocabularyResult:
    side_id: str
    action: str
    status: str
    text: str
    verified_word_count: int
    target_word_count: int


def _user_key(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value:
        raise ValueError("Side 5 requires a non-empty user_id")
    return value[:_MAX_USER_ID_CHARS]


def run_core_vocabulary(user_id: str, action: str, answer: str = "") -> CoreVocabularyResult:
    """Run one bounded Side 5 action for one identified learner."""
    key = _user_key(user_id)
    selected_action = str(action or "").strip().lower()
    if selected_action not in {"daily", "review", "quiz", "answer"}:
        raise ValueError("unsupported Side 5 action")

    if selected_action == "quiz":
        text = start_quiz(key)
    elif selected_action == "answer":
        text = grade_quiz(key, answer)
        if text is None:
            raise ValueError("answer must be A, B, or C")
    else:
        selected = select_daily_words(key, 3)
        lines = ["📘 今日の英単語コアイメージ（確認済みローカル辞書）", ""]
        for word, core_image, example in selected:
            lines.extend((f"• {word}", f"  コアイメージ: {core_image}", f"  例: {example}"))
        lines.extend(("", "クイズを始めるには「クイズ」と送ってください。"))
        text = "\n".join(lines) if selected else "現在、確認済みの出題可能な単語がありません。"

    return CoreVocabularyResult(
        side_id=SIDE_ID,
        action=selected_action,
        status="READY" if _ENTRIES else "BLOCKED",
        text=text,
        verified_word_count=len(_ENTRIES),
        target_word_count=TARGET_WORDS,
    )
