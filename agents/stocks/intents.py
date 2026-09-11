"""Intent helpers for the stock feature."""
from __future__ import annotations


def is_stock_intent(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return any(k in lowered for k in ("株", "株価", "銘柄", "ticker", "stock", "stocks", "share price"))
