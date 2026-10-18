"""Persistent, local-only vocabulary rotation and quiz state for the English agent."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from agents.english.core_image import _ENTRIES

DB_PATH = os.environ.get(
    "CHAT_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chat.db"),
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS english_word_history (
            user_id TEXT NOT NULL,
            word TEXT NOT NULL,
            shown_at TEXT NOT NULL,
            PRIMARY KEY (user_id, word)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS english_pending_quiz (
            user_id TEXT PRIMARY KEY,
            word TEXT NOT NULL,
            options_json TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    return conn


def _user_key(user_id: str) -> str:
    return str(user_id or "anonymous").strip()[:200] or "anonymous"


def _lexicon() -> list[tuple[str, str, str]]:
    """Use only reviewed local entries; never synthesize an unreviewed definition."""
    return [
        (word, entry.core_image, entry.example)
        for word, entry in sorted(_ENTRIES.items())
        if entry.core_image.strip() and entry.example.strip()
    ]


def select_daily_words(user_id: str, limit: int = 3) -> list[tuple[str, str, str]]:
    """Choose least-recently shown reviewed words, persist history, and rotate after exhaustion."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")
    words = _lexicon()
    if not words:
        return []
    key = _user_key(user_id)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        seen = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT word, shown_at FROM english_word_history WHERE user_id=?", (key,)
            )
        }
        # Never repeat a word while unseen entries remain. When the entire
        # reviewed lexicon has been seen, the least-recently-seen entries rotate first.
        ranked = sorted(words, key=lambda item: (item[0] in seen, seen.get(item[0], ""), item[0]))
        selected = ranked[: min(limit, len(words))]
        for word, _, _ in selected:
            conn.execute(
                """INSERT INTO english_word_history(user_id, word, shown_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, word) DO UPDATE SET shown_at=excluded.shown_at""",
                (key, word, now),
            )
    return selected


def create_quiz(user_id: str) -> str:
    """Quiz the words most recently shown; only seed a new batch if no words were shown yet."""
    key = _user_key(user_id)
    with _connect() as conn:
        recent_words = [
            row[0]
            for row in conn.execute(
                """SELECT word FROM english_word_history
                   WHERE user_id=? ORDER BY shown_at DESC, word ASC LIMIT 3""",
                (key,),
            )
        ]
    lexicon = _lexicon()
    by_word = {item[0]: item for item in lexicon}
    words = [by_word[word] for word in recent_words if word in by_word]
    if not words:
        words = select_daily_words(user_id, 3)
    if not words:
        return "現在、出題できる確認済み単語がありません。"
    target = words[0]
    distractors = [item for item in words[1:] if item[0] != target[0]]
    if len(distractors) < 2:
        pool = [item for item in lexicon if item[0] != target[0] and item[0] not in {d[0] for d in distractors}]
        distractors.extend(pool[: 2 - len(distractors)])
    options = [target] + distractors[:2]
    # A/B/C are stable for a given user and batch; no randomness or network access.
    user_sum = sum(ord(ch) for ch in key)
    shift = user_sum % len(options)
    options = options[shift:] + options[:shift]
    labels = ("a", "b", "c")
    correct = labels[options.index(target)]
    with _connect() as conn:
        conn.execute(
            """INSERT INTO english_pending_quiz(user_id, word, options_json, correct_option, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET word=excluded.word,
                 options_json=excluded.options_json, correct_option=excluded.correct_option,
                 created_at=excluded.created_at""",
            (key, target[0], json.dumps([item[0] for item in options]),
             correct, datetime.now(timezone.utc).isoformat()),
        )
    lines = ["📝 英単語クイズ", "", f"「{target[1]}」に最も近い単語は？", ""]
    lines.extend(f"{label.upper()}. {item[0]}" for label, item in zip(labels, options))
    lines.extend(["", "答えは A / B / C で送ってください。"])
    return "\n".join(lines)


def has_pending_quiz(user_id: str) -> bool:
    with _connect() as conn:
        return conn.execute(
            "SELECT 1 FROM english_pending_quiz WHERE user_id=?", (_user_key(user_id),)
        ).fetchone() is not None


def grade_pending_quiz(user_id: str, answer: str) -> str | None:
    """Grade only an active quiz, then clear it so stale answers cannot be marked correct."""
    value = (answer or "").strip().lower()
    if value not in {"a", "b", "c"}:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT word, correct_option FROM english_pending_quiz WHERE user_id=?",
            (_user_key(user_id),),
        ).fetchone()
        if row is None:
            return None
        word, correct = row
        conn.execute("DELETE FROM english_pending_quiz WHERE user_id=?", (_user_key(user_id),))
    entry = _ENTRIES.get(word)
    explanation = entry.core_image if entry else word
    if value == correct:
        return f"✅ 正解！\n\n{word}\nコアイメージ: {explanation}\n\n次は「クイズ」または「単語」と送ってください。"
    return f"❌ 惜しい！正解は {correct.upper()}. {word} です。\n\nコアイメージ: {explanation}\n\n「クイズ」で再挑戦できます。"
