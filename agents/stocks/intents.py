"""Intent helpers for the stock feature."""
from __future__ import annotations

import re


_ENGLISH_STOCK_RE = re.compile(
    r"\b(?:ticker|stock|stocks|share\s+price|stock\s+price)\b", re.IGNORECASE
)


def is_stock_intent(text: str) -> bool:
    """Return True only for explicit stock-related terms."""
    normalized = (text or "").strip().lower()
    if any(k in normalized for k in ("株", "株価", "銘柄")):
        return True
    return bool(_ENGLISH_STOCK_RE.search(text or ""))
