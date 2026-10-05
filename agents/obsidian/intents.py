"""Explicit Obsidian operation intent detection and safe normalization."""
from __future__ import annotations

import os
import re
import unicodedata


_OPERATION_RE = re.compile(
    r"^obsidian\s*(?:に|へ)\s*(?:保存|記録|追記|追加)\b",
    re.IGNORECASE,
)
_READ_RE = re.compile(
    r"^obsidian\s*(?:を|から)\s*(?:読む|読んで|表示して)\b",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(
    r"^obsidian\s*(?:で|から)\s*(?:検索|探して)\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(
    r"^obsidian\s*(?:の)?\s*(?:一覧|リスト)\s*$",
    re.IGNORECASE,
)
_NATURAL_RECORD_RE = re.compile(
    r'^obsidian\s*(?:に|へ)\s*[「『"“](?P<content>[\s\S]+?)[」』"”]'
    r"\s*(?:と)?\s*(?:保存|記録|追記|追加)して[。．.!！]*$",
    re.IGNORECASE,
)

_DEFAULT_NOTE_PATH = "LINE-Inbox.md"


def _default_note_path() -> str:
    """Return a bounded configurable destination for natural capture commands."""
    value = os.environ.get("OBSIDIAN_DEFAULT_NOTE_PATH", _DEFAULT_NOTE_PATH).strip()
    if not value:
        value = _DEFAULT_NOTE_PATH
    path = __import__("pathlib").Path(value)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ValueError("OBSIDIAN_DEFAULT_NOTE_PATH must be a relative .md path")
    return path.as_posix()


def normalize_obsidian_command(raw_message: str) -> str | None:
    """Normalize explicit and natural Obsidian commands to a safe bounded form."""
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return None

    natural_match = _NATURAL_RECORD_RE.fullmatch(text)
    if natural_match:
        content = natural_match.group("content").strip()
        if not content:
            return None
        return f"Obsidianに追記 {_default_note_path()}: {content}"

    if (
        _OPERATION_RE.match(text)
        or _READ_RE.match(text)
        or _SEARCH_RE.match(text)
        or _LIST_RE.fullmatch(text)
    ):
        return text
    return None


def is_obsidian_intent(raw_message: str) -> bool:
    """Match only explicit Obsidian commands."""
    return normalize_obsidian_command(raw_message) is not None
