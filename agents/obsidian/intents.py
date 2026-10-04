"""Explicit Obsidian operation intent detection."""
from __future__ import annotations

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


def is_obsidian_intent(raw_message: str) -> bool:
    """Match only explicit Obsidian read/write commands."""
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return False
    return bool(_OPERATION_RE.match(text) or _READ_RE.match(text))
