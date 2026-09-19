"""Persistent, privacy-light learning state for the English AI coach.

Only small aggregate signals are stored: turn count and a few deterministic
mistake categories. Raw learner messages are not stored by this module.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass

DB_PATH = os.environ.get(
    "CHAT_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chat.db"),
)

_MAX_USER_ID_CHARS = 200
_MAX_WEAK_POINTS = 4


@dataclass(frozen=True)
class EnglishLearningProfile:
    turns: int
    weak_points: tuple[str, ...]

    @property
    def level(self) -> str:
        if self.turns < 5:
            return "beginner"
        if self.turns < 15:
            return "intermediate"
        return "advanced"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS english_learning_profiles(
            user_id TEXT PRIMARY KEY,
            turns INTEGER NOT NULL DEFAULT 0,
            weak_points TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def _normalize_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    return value[:_MAX_USER_ID_CHARS] or "anonymous"


def _detect_mistakes(text: str) -> tuple[str, ...]:
    value = str(text or "").strip().lower()
    tags: set[str] = set()
    if re.search(r"\b(i|you|we|they)\s+(?:really\s+)?has\b", value) or re.search(
        r"\b(he|she|it)\s+(?:really\s+)?have\b", value
    ):
        tags.add("subject_verb_agreement")
    if re.search(r"\b(i|he|she|it|you|we|they)\s+(?:is|are|am)\s+(?:go|eat|work|study|learn)\b", value):
        tags.add("verb_form")
    if re.search(r"\b(?:yesterday|last\s+(?:week|month|year))\b[^.!?]*\b(go|eat|see|have|make|do)\b", value):
        tags.add("past_tense")
    if re.search(r"\bwant\s+(?:to\s+)?\w+\b", value) and not re.search(r"\bwant\s+to\s+\w+\b", value):
        tags.add("infinitive")
    return tuple(sorted(tags))


def load_profile(user_id: str) -> EnglishLearningProfile:
    key = _normalize_user_id(user_id)
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT turns, weak_points FROM english_learning_profiles WHERE user_id=?",
                (key,),
            ).fetchone()
    except Exception:
        return EnglishLearningProfile(turns=0, weak_points=())
    if row is None:
        return EnglishLearningProfile(turns=0, weak_points=())
    try:
        counts = json.loads(row[1] or "{}")
    except (TypeError, ValueError):
        counts = {}
    ranked = sorted(
        (
            (str(name), int(count))
            for name, count in counts.items()
            if isinstance(name, str) and isinstance(count, int)
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return EnglishLearningProfile(
        turns=max(0, int(row[0] or 0)),
        weak_points=tuple(name for name, _ in ranked[:_MAX_WEAK_POINTS]),
    )


def record_observation(user_id: str, text: str) -> EnglishLearningProfile:
    key = _normalize_user_id(user_id)
    tags = _detect_mistakes(text)
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT turns, weak_points FROM english_learning_profiles WHERE user_id=?",
                (key,),
            ).fetchone()
            turns = max(0, int(row[0] if row else 0)) + 1
            try:
                counts = json.loads(row[1] if row else "{}")
            except (TypeError, ValueError):
                counts = {}
            for tag in tags:
                counts[tag] = int(counts.get(tag, 0)) + 1
            conn.execute(
                """
                INSERT INTO english_learning_profiles(user_id, turns, weak_points, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    turns=excluded.turns,
                    weak_points=excluded.weak_points,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (key, turns, json.dumps(counts, ensure_ascii=False)),
            )
    except Exception:
        return load_profile(key)
    return load_profile(key)


def profile_prompt(profile: EnglishLearningProfile) -> str:
    weak = ", ".join(profile.weak_points) if profile.weak_points else "none detected yet"
    return (
        f"Learning profile: level={profile.level}; repeated mistake areas={weak}. "
        "Use this only to adapt examples and the next exercise. "
        "Do not mention internal profile data or claim that these areas are definitive."
    )


__all__ = [
    "EnglishLearningProfile",
    "DB_PATH",
    "load_profile",
    "profile_prompt",
    "record_observation",
]
