"""Intent helpers for voice and AI speaker requests."""
from __future__ import annotations

import re


_ENGLISH_VOICE_RE = re.compile(r"\b(?:voice|voice\s+assistant|speaker)\b", re.IGNORECASE)


def is_voice_intent(text: str) -> bool:
    """Return True only for explicit voice-related terms."""
    value = text or ""
    lowered = value.strip().lower()
    if any(k in lowered for k in ("音声", "ボイス", "aiスピーカー", "しゃべって")):
        return True
    return bool(_ENGLISH_VOICE_RE.search(value))
