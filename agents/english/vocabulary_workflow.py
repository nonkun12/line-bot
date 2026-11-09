"""Human-reviewed, persistent workflow for adding English vocabulary.

Candidates are never promoted by submission. Promotion requires a trusted caller to
supply a reviewed entry and an authorization callback; the callback fails closed.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Callable, Mapping

from agents.english.progress import DB_PATH
from agents.english.vocabulary_registry import normalize_headword, validate_new_headwords


@dataclass(frozen=True)
class CandidateReceipt:
    candidate_id: int
    word: str
    status: str


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS english_vocabulary_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            submitted_by TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
            submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS english_approved_vocabulary (
            word TEXT PRIMARY KEY,
            entry_json TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    return conn


def submit_word_candidate(word: str, submitted_by: str) -> CandidateReceipt:
    """Persist a new candidate as pending; never add it to the learning lexicon."""
    normalized = normalize_headword(word)
    actor = str(submitted_by or "").strip()[:200]
    if not actor:
        raise ValueError("submitter identity is required")
    validate_new_headwords([normalized])
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM english_approved_vocabulary WHERE word=?", (normalized,)
        ).fetchone():
            raise ValueError(f"word is already approved: {normalized}")
        existing = conn.execute(
            "SELECT id, status FROM english_vocabulary_candidates WHERE word=?",
            (normalized,),
        ).fetchone()
        if existing:
            if existing[1] == "pending":
                raise ValueError(f"candidate is already pending: {normalized} (#{existing[0]})")
            raise ValueError(f"candidate was already reviewed: {normalized} (#{existing[0]})")
        cursor = conn.execute(
            "INSERT INTO english_vocabulary_candidates(word, submitted_by, status) VALUES (?, ?, 'pending')",
            (normalized, actor),
        )
        return CandidateReceipt(int(cursor.lastrowid), normalized, "pending")


def list_pending_candidates(limit: int = 50) -> tuple[dict, ...]:
    """Return a bounded review queue without exposing submitter message contents."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer from 1 to 200")
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, word, submitted_by, submitted_at
               FROM english_vocabulary_candidates WHERE status='pending'
               ORDER BY submitted_at, id LIMIT ?""",
            (limit,),
        ).fetchall()
    return tuple(
        {"candidate_id": row[0], "word": row[1], "submitted_by": row[2], "submitted_at": row[3]}
        for row in rows
    )


def approve_word_candidate(
    candidate_id: int,
    entry: Mapping[str, object],
    reviewer_id: str,
    *,
    authorize_reviewer: Callable[[str], bool] | None = None,
) -> str:
    """Atomically promote a fully reviewed entry after explicit reviewer authorization."""
    reviewer = str(reviewer_id or "").strip()[:200]
    if not reviewer or authorize_reviewer is None or not authorize_reviewer(reviewer):
        raise PermissionError("authorized human reviewer required")
    required = ("word", "pronunciation", "core_image", "parts", "related", "example")
    if not isinstance(entry, Mapping) or any(key not in entry for key in required):
        raise ValueError("reviewed entry is missing required fields")
    word = normalize_headword(str(entry["word"]))
    clean = {
        "word": word,
        "pronunciation": str(entry["pronunciation"]).strip(),
        "core_image": str(entry["core_image"]).strip(),
        "parts": str(entry["parts"]).strip(),
        "related": tuple(str(item).strip() for item in entry["related"]),
        "example": str(entry["example"]).strip(),
        "note": str(entry.get("note", "")).strip(),
    }
    if not all(clean[key] for key in ("pronunciation", "core_image", "parts", "example")):
        raise ValueError("reviewed entry contains empty required content")
    if not clean["related"] or any(not item for item in clean["related"]):
        raise ValueError("reviewed entry requires non-empty related words")
    validate_new_headwords([word])
    from agents.english.core_image import WordEntry

    reviewed = WordEntry(**clean)
    payload = json.dumps(
        {
            "word": reviewed.word,
            "pronunciation": reviewed.pronunciation,
            "core_image": reviewed.core_image,
            "parts": reviewed.parts,
            "related": list(reviewed.related),
            "example": reviewed.example,
            "note": reviewed.note,
        },
        ensure_ascii=False,
    )
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT word, status FROM english_vocabulary_candidates WHERE id=?",
            (int(candidate_id),),
        ).fetchone()
        if row is None or row[1] != "pending" or row[0] != word:
            raise ValueError("candidate does not exist, is not pending, or word does not match")
        if conn.execute(
            "SELECT 1 FROM english_approved_vocabulary WHERE word=?", (word,)
        ).fetchone():
            raise ValueError(f"word is already approved: {word}")
        conn.execute(
            "INSERT INTO english_approved_vocabulary(word, entry_json, approved_by) VALUES (?, ?, ?)",
            (word, payload, reviewer),
        )
        conn.execute(
            """UPDATE english_vocabulary_candidates
               SET status='approved', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='pending'""",
            (reviewer, int(candidate_id)),
        )
    return word


def reject_word_candidate(
    candidate_id: int,
    reviewer_id: str,
    reason: str,
    *,
    authorize_reviewer: Callable[[str], bool] | None = None,
) -> None:
    """Reject a pending candidate; only an authorized reviewer may change its state."""
    reviewer = str(reviewer_id or "").strip()[:200]
    note = str(reason or "").strip()[:500]
    if not reviewer or not note or authorize_reviewer is None or not authorize_reviewer(reviewer):
        raise PermissionError("authorized reviewer and a rejection reason are required")
    with _connect() as conn:
        cursor = conn.execute(
            """UPDATE english_vocabulary_candidates
               SET status='rejected', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP, review_note=?
               WHERE id=? AND status='pending'""",
            (reviewer, note, int(candidate_id)),
        )
        if cursor.rowcount != 1:
            raise ValueError("pending candidate not found")


def load_approved_entries():
    """Load only human-approved entries for runtime vocabulary and quizzes."""
    from agents.english.core_image import WordEntry

    with _connect() as conn:
        rows = conn.execute(
            "SELECT word, entry_json FROM english_approved_vocabulary ORDER BY word"
        ).fetchall()
    entries = []
    for word, payload in rows:
        data = json.loads(payload)
        if data.get("word") != word:
            raise RuntimeError("approved vocabulary row failed integrity check")
        entries.append(WordEntry(**{**data, "related": tuple(data["related"])}))
    return tuple(entries)
