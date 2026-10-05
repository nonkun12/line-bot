"""Structured learning loop for English core-image vocabulary.

The loop is deterministic and provider-neutral. Model generation is not required
to grade the bounded recall exercises, keeping the first learning layer safe.
"""
from __future__ import annotations

from dataclasses import dataclass

from .core_image import CoreImageEntry, get_core_image


@dataclass(frozen=True)
class ContextExample:
    situation: str
    sentence: str
    Japanese_hint: str


@dataclass(frozen=True)
class UsageContrast:
    label: str
    explanation: str


@dataclass(frozen=True)
class RecallPrompt:
    prompt: str
    expected_word: str


@dataclass(frozen=True)
class CoreImageLesson:
    entry: CoreImageEntry
    contexts: tuple[ContextExample, ...]
    usage: tuple[UsageContrast, ...]
    recall: RecallPrompt


_LEARNING_CONTEXTS: dict[str, tuple[ContextExample, ...]] = {
    "improve": (
        ContextExample("英語力", "I want to improve my English.", "英語を今より良くする"),
        ContextExample("スキル", "She improved her writing skills.", "文章を書く力を向上させる"),
    ),
    "schedule": (
        ContextExample("確認", "Let me check my schedule.", "予定を確認する"),
        ContextExample("予定を組む", "I scheduled a meeting for Friday.", "会議を金曜日に予定した"),
    ),
    "recommend": (
        ContextExample("本", "Can you recommend a good book?", "良い本を勧めてもらう"),
        ContextExample("店", "Can you recommend a restaurant?", "良い店を勧めてもらう"),
    ),
}

_USAGE: dict[str, tuple[UsageContrast, ...]] = {
    "improve": (
        UsageContrast("improve", "今ある状態・能力をより良くする方向に動かす"),
        UsageContrast("fix", "壊れた・間違ったものを直すことに焦点を置く"),
    ),
    "schedule": (
        UsageContrast("schedule", "予定を時間に配置して管理する"),
        UsageContrast("plan", "何をするかという計画全体を考えることに焦点を置く"),
    ),
    "recommend": (
        UsageContrast("recommend", "相手に合いそうなものとして勧める"),
        UsageContrast("suggest", "選択肢・考えを提案することに焦点を置く"),
    ),
}


def build_core_image_lesson(word: str) -> CoreImageLesson | None:
    """Build one bounded lesson; unknown words fail closed."""
    entry = get_core_image(word)
    if entry is None:
        return None
    contexts = _LEARNING_CONTEXTS.get(entry.word, ())
    usage = _USAGE.get(entry.word, ())
    if not contexts or not usage:
        return None
    return CoreImageLesson(
        entry=entry,
        contexts=contexts,
        usage=usage,
        recall=RecallPrompt(
            prompt=f"「{entry.core_image}」に近い英単語を答えてください。",
            expected_word=entry.word,
        ),
    )


def grade_recall(word: str, answer: str) -> bool:
    """Grade only the exact normalized target; no fuzzy or model judgment."""
    target = str(word or "").strip().lower()
    candidate = str(answer or "").strip().lower()
    return bool(target) and candidate == target


def next_core_image_word(current_word: str) -> str | None:
    """Return the next bounded word in a deterministic cycle."""
    words = ("improve", "schedule", "recommend")
    current = str(current_word or "").strip().lower()
    if current not in words:
        return words[0] if words else None
    index = words.index(current)
    return words[(index + 1) % len(words)]


__all__ = [
    "ContextExample",
    "CoreImageLesson",
    "RecallPrompt",
    "UsageContrast",
    "build_core_image_lesson",
    "grade_recall",
    "next_core_image_word",
]
