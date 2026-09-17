"""Intent helpers for the stock feature."""
from __future__ import annotations

import re


_ENGLISH_STOCK_RE = re.compile(
    r"\b(?:ticker|stock|stocks|share\s+price|stock\s+price)\b", re.IGNORECASE
)
_ANALYSIS_WITH_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{4}|[A-Za-z]{2,6}(?:\.[A-Za-z]{1,3})?)"
    r"\s*(?:の|を)?\s*(?:分析|テクニカル|指標|チャート|analy(?:ze|sis)|technical)",
    re.IGNORECASE,
)


def is_stock_intent(text: str) -> bool:
    """Return True for explicit market requests or a ticker + analysis request."""
    normalized = (text or "").strip().lower()
    if any(k in normalized for k in ("株", "株価", "銘柄")):
        return True
    return bool(
        _ENGLISH_STOCK_RE.search(text or "")
        or _ANALYSIS_WITH_TICKER_RE.search(text or "")
    )
