"""Intent recognition for global market and FX requests."""
from __future__ import annotations

import re


_ENGLISH_MARKET_RE = re.compile(
    r"\b(?:dow|dow\s+jones|forex|fx|exchange\s+rate|currency|currencies)\b",
    re.IGNORECASE,
)


def is_market_intent(text: str) -> bool:
    value = (text or "").strip().casefold()
    japanese_terms = (
        "nyダウ",
        "nyダウ平均",
        "ダウ平均",
        "ダウ",
        "世界株価",
        "世界の株価",
        "為替",
        "ドル円",
        "ユーロドル",
        "ポンドドル",
        "豪ドル",
        "ユーロ円",
        "ポンド円",
        "ドルスイス",
        "ドルカナダ",
        "ドル人民元",
        "通貨",
    )
    if any(term.casefold() in value for term in japanese_terms):
        return True
    return bool(_ENGLISH_MARKET_RE.search(text or ""))
