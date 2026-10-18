"""Persistent, varied vocabulary quizzes backed by the reviewed local core-image lexicon."""
from __future__ import annotations

import json
import random
import re
import sqlite3

from agents.english import progress
from agents.english.core_image import get_core_image_quiz_entries

_LABELS = ("A", "B", "C")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(progress.DB_PATH, timeout=10)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS english_quiz_sessions (
            user_id TEXT PRIMARY KEY,
            current_word TEXT NOT NULL DEFAULT '',
            correct_option TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '[]',
            previous_word TEXT NOT NULL DEFAULT '',
            older_word TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    try:
        conn.execute("ALTER TABLE english_quiz_sessions ADD COLUMN older_word TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            conn.close()
            raise
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS english_vocabulary_batches (
            user_id TEXT PRIMARY KEY,
            words_json TEXT NOT NULL,
            shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def _user_key(user_id: str) -> str:
    return str(user_id or "").strip()[:200] or "anonymous"


def record_vocabulary_batch(user_id: str, words: list[str]) -> None:
    """Persist the exact reviewed words most recently shown to this user."""
    key = _user_key(user_id)
    valid = {entry.word for entry in get_core_image_quiz_entries()}
    batch = list(dict.fromkeys(word for word in words if isinstance(word, str) and word in valid))[:10]
    with _connect() as conn:
        conn.execute(
            """INSERT INTO english_vocabulary_batches(user_id, words_json, shown_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                 words_json=excluded.words_json, shown_at=CURRENT_TIMESTAMP""",
            (key, json.dumps(batch, ensure_ascii=False)),
        )


def start_quiz(user_id: str) -> str:
    """Create a new three-choice question, avoiding the user's last two words."""
    entries = list(get_core_image_quiz_entries())
    if len(entries) < 3:
        return "クイズ用の単語が不足しています。辞書を確認してください。"

    key = _user_key(user_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT current_word, previous_word, older_word FROM english_quiz_sessions WHERE user_id=?",
            (key,),
        ).fetchone()
        avoid = {str(value) for value in row or () if value}
        batch_row = conn.execute(
            "SELECT words_json FROM english_vocabulary_batches WHERE user_id=?", (key,)
        ).fetchone()
        by_word = {entry.word: entry for entry in entries}
        batch = []
        if batch_row:
            try:
                stored_words = json.loads(batch_row[0])
            except (TypeError, ValueError):
                stored_words = []
            if isinstance(stored_words, list):
                batch = [by_word[word] for word in stored_words if isinstance(word, str) and word in by_word]
        # Prefer the exact words shown in the latest vocabulary batch. After a
        # learner has exhausted those words, fall back to the reviewed lexicon.
        pool = [entry for entry in batch if entry.word not in avoid]
        if not pool:
            pool = batch
        if not pool:
            pool = [entry for entry in entries if entry.word not in avoid]
        if len(pool) < 1:
            pool = entries
        correct = random.choice(pool)
        distractor_pool = [entry for entry in batch if entry.word != correct.word]
        if len(distractor_pool) < 2:
            distractor_pool.extend(
                entry for entry in entries
                if entry.word != correct.word and entry not in distractor_pool
            )
        distractors = random.sample(distractor_pool, 2)
        choices = [correct, *distractors]
        random.shuffle(choices)
        correct_option = _LABELS[choices.index(correct)]
        conn.execute(
            """
            INSERT INTO english_quiz_sessions
                (user_id, current_word, correct_option, options_json, previous_word, older_word, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                current_word=excluded.current_word,
                correct_option=excluded.correct_option,
                options_json=excluded.options_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                key,
                correct.word,
                correct_option,
                json.dumps([{"label": label, "word": entry.word} for label, entry in zip(_LABELS, choices)],
                           ensure_ascii=False),
                str(row[1] or "") if row else "",
                str(row[2] or "") if row else "",
            ),
        )

    lines = [
        "📝 英単語コアイメージクイズ",
        "",
        "次のコアイメージに合う英単語は？",
        correct.core_image,
        "",
    ]
    lines.extend(f"{label}. {entry.word}" for label, entry in zip(_LABELS, choices))
    lines.extend(["", "答えは A / B / C で送ってください。"])
    return "\n".join(lines)


def grade_quiz(user_id: str, answer_text: str) -> str | None:
    """Grade against the active per-user question; never assume A is correct."""
    match = re.fullmatch(r"(?:answer\s*)?([abc])(?:[.\)\s]+)?", (answer_text or "").strip(), re.I)
    if not match:
        return None
    answer = match.group(1).upper()
    key = _user_key(user_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT current_word, correct_option, options_json FROM english_quiz_sessions WHERE user_id=?",
            (key,),
        ).fetchone()
        if not row or not row[0] or row[1] not in _LABELS:
            return "先に「クイズ」と送って問題を出してください。"
        word, correct_option, options_json = row
        try:
            options = json.loads(options_json)
        except (TypeError, ValueError):
            options = []
        conn.execute(
            """
            UPDATE english_quiz_sessions
            SET older_word=previous_word, previous_word=current_word, current_word='', correct_option='', options_json='[]',
                updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?
            """,
            (key,),
        )

    if answer == correct_option:
        result = f"✅ 正解！ {word}"
    else:
        result = f"❌ 惜しい！正解は {correct_option}. {word} です。"
    from agents.english.core_image import explain_core_image
    return result + "\n\n" + explain_core_image(word) + "\n\n次の問題は「クイズ」と送ってください。"
