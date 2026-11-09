"""Fail-closed duplicate prevention for the reviewed English vocabulary."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

_REGISTRY_PATH = Path(__file__).with_name("vocabulary_registry.json")
_WORD_RE = re.compile(r"^[a-z][a-z'-]{0,63}$")


def normalize_headword(word: str) -> str:
    """Normalize a single English headword or reject malformed input."""
    value = str(word or "").strip().lower()
    if not _WORD_RE.fullmatch(value):
        raise ValueError(f"invalid English headword: {word!r}")
    return value


def load_vocabulary_registry() -> dict:
    """Load the committed registry; missing or malformed data fails closed."""
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    required = ("current_headwords", "historical_seen_headwords",
                "reserved_candidate_headwords", "reserved_flashcard_headwords",
                "blocked_headwords")
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list) for key in required):
        raise RuntimeError("English vocabulary registry is missing required lists")
    blocked = set(data["blocked_headwords"])
    expected = set(data["current_headwords"]) | set(data["historical_seen_headwords"]) | set(
        data["reserved_candidate_headwords"]
    ) | set(data["reserved_flashcard_headwords"])
    if blocked != expected:
        raise RuntimeError("English vocabulary registry blocked list is out of sync")
    if len(blocked) != len(data["blocked_headwords"]):
        raise RuntimeError("English vocabulary registry contains duplicate blocked words")
    return data


def classify_headword(word: str, registry: dict | None = None) -> str:
    """Return current, historical, reserved_candidate, flashcard, or unseen."""
    value = normalize_headword(word)
    data = registry or load_vocabulary_registry()
    for field, status in (
        ("current_headwords", "current"),
        ("historical_seen_headwords", "historical"),
        ("reserved_candidate_headwords", "reserved_candidate"),
        ("reserved_flashcard_headwords", "flashcard"),
    ):
        if value in data[field]:
            return status
    return "unseen"


def validate_new_headwords(words: Iterable[str]) -> tuple[str, ...]:
    """Reject previously used words and duplicates within a proposed batch."""
    normalized = tuple(normalize_headword(word) for word in words)
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate headword inside proposed vocabulary batch")
    data = load_vocabulary_registry()
    blocked = set(data["blocked_headwords"])
    conflicts = sorted(set(normalized) & blocked)
    if conflicts:
        raise ValueError("previously registered or reserved headwords: " + ", ".join(conflicts))
    return normalized


def validate_current_headwords(words: Iterable[str]) -> None:
    """Require exact agreement between source dictionary and registry."""
    normalized = tuple(normalize_headword(word) for word in words)
    if len(normalized) != len(set(normalized)):
        raise RuntimeError("duplicate headword in English dictionary")
    data = load_vocabulary_registry()
    if set(normalized) != set(data["current_headwords"]):
        missing = sorted(set(normalized) - set(data["current_headwords"]))
        stale = sorted(set(data["current_headwords"]) - set(normalized))
        raise RuntimeError(
            f"English dictionary/registry mismatch; unregistered={missing}, stale={stale}"
        )
