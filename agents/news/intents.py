"""Intent helpers for AI news requests."""
from __future__ import annotations

import re


_AI_NEWS_ENGLISH_RE = re.compile(
    r"(?<![A-Za-z0-9_])ai\s+news(?![A-Za-z0-9_])", re.IGNORECASE
)


def is_ai_news_intent(text: str) -> bool:
    """Return True only for explicit AI-news requests."""
    value = text or ""
    lowered = value.strip().lower()
    if any(k in lowered for k in ("aiニュース", "ai ニュース", "人工知能ニュース")):
        return True
    return bool(_AI_NEWS_ENGLISH_RE.search(value))
