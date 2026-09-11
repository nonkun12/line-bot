"""Intent helpers for AI news requests."""
from __future__ import annotations


def is_ai_news_intent(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return any(k in lowered for k in ("ai news", "aiニュース", "ai ニュース", "人工知能ニュース"))
