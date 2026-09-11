"""Intent helpers for the English-learning feature."""
from __future__ import annotations

import re


def classify_english_mode(text: str) -> str:
    """Classify a learning request into a deterministic mode."""
    lowered = (text or "").strip().lower()
    if re.fullmatch(r"(?:answer\s*)?[abc](?:[.\)\s]+)?", lowered):
        return "quiz_answer"
    if any(k in lowered for k in ("クイズ", "quiz", "問題")):
        return "quiz"
    if any(k in lowered for k in ("単語", "vocabulary", "word")):
        return "vocabulary"
    if any(k in lowered for k in ("文法", "grammar")):
        return "grammar"
    if any(k in lowered for k in ("会話", "英会話", "conversation", "speaking")):
        return "conversation"
    if any(k in lowered for k in ("復習", "review", "復習して")):
        return "review"
    return "lesson"


def is_english_learning_intent(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if re.fullmatch(r"(?:answer\s*)?[abc](?:[.\)\s]+)?", lowered):
        return True
    return any(
        k in lowered
        for k in (
            "英語",
            "英会話",
            "英単語",
            "英文",
            "english",
            "vocabulary",
            "speaking",
            "grammar",
            "quiz",
            "クイズ",
            "単語",
            "文法",
            "会話",
            "復習",
            "review",
        )
    )
