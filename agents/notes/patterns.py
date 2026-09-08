from __future__ import annotations

import re
import unicodedata
from typing import Optional

_EXPLICIT_SAVE_NOTE_RE = re.compile(
    r"^(.+?)(?:を)?\s*メモして[。！!？?]?\s*$"
)
_SAVE_NOTE_TO_RE = re.compile(
    r"^メモに\s*[:：、,]?\s*(.+?)\s*保存して[。！!？?]?\s*$"
)


def extract_explicit_note_body(raw_message: str) -> Optional[str]:
    """Return the note body for an explicit save request, otherwise None."""
    text = unicodedata.normalize("NFKC", (raw_message or "").strip())
    if not text:
        return None

    match = _SAVE_NOTE_TO_RE.fullmatch(text)
    if match:
        body = match.group(1).strip()
        return body or None

    if text.startswith("メモして"):
        body = re.sub(r"^メモして\s*", "", text).strip()
        return body or None

    match = _EXPLICIT_SAVE_NOTE_RE.fullmatch(text)
    if match:
        body = match.group(1).strip()
        return body or None

    return None


def is_explicit_save_note(raw_message: str) -> bool:
    return extract_explicit_note_body(raw_message) is not None
