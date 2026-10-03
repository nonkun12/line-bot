"""Core-image vocabulary foundation for English learning.

A core image is the small conceptual center that connects a word's common
meanings instead of treating each Japanese translation as a separate fact.
This module is deterministic and provider-neutral so it can be reused by
LINE, voice, hand-sign-adjacent learning flows, or another UI later.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreImageEntry:
    word: str
    core_image: str
    common_senses: tuple[str, ...]
    example: str


_CORE_IMAGES: tuple[CoreImageEntry, ...] = (
    CoreImageEntry(
        word="improve",
        core_image="今より良い状態へ持っていく",
        common_senses=("改善する", "向上させる"),
        example="I want to improve my English.",
    ),
    CoreImageEntry(
        word="schedule",
        core_image="時間の流れの中に予定を置いて管理する",
        common_senses=("予定", "予定を組む"),
        example="Let me check my schedule.",
    ),
    CoreImageEntry(
        word="recommend",
        core_image="相手に合うものとして勧める",
        common_senses=("おすすめする", "推薦する"),
        example="Can you recommend a good book?",
    ),
)


def get_core_image(word: str) -> CoreImageEntry | None:
    """Return a deterministic core-image entry for a word."""
    normalized = str(word or "").strip().lower()
    if not normalized:
        return None
    for entry in _CORE_IMAGES:
        if entry.word == normalized:
            return entry
    return None


def available_core_images() -> tuple[CoreImageEntry, ...]:
    """Return the bounded built-in vocabulary set."""
    return _CORE_IMAGES


def format_core_image_lesson(word: str) -> str | None:
    """Format one word around its core image, not a translation list."""
    entry = get_core_image(word)
    if entry is None:
        return None
    senses = " / ".join(entry.common_senses)
    return (
        f"🔑 {entry.word}\n"
        f"コアイメージ: {entry.core_image}\n"
        f"主な意味: {senses}\n"
        f"例: {entry.example}"
    )


__all__ = [
    "CoreImageEntry",
    "available_core_images",
    "format_core_image_lesson",
    "get_core_image",
]
