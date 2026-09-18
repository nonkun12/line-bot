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
        "s&p500",
        "sp500",
        "nasdaq",
        "ナスダック",
        "日経",
        "日経225",
        "nikkei",
        "dax",
        "ftse",
        "ハンセン",
        "hang seng",
        "上海総合",
        "kospi",
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

_INDEX_TERMS = {
    "dow": ("nyダウ", "nyダウ平均", "ダウ平均", "ダウ", "dow", "dow jones"),
    "sp500": ("s&p500", "sp500", "s&p 500", "s\u0026p 500"),
    "nasdaq": ("nasdaq", "ナスダック"),
    "nikkei": ("日経225", "日経２２５", "日経平均", "日経", "nikkei"),
    "dax": ("dax",),
    "ftse": ("ftse100", "ftse 100", "ftse"),
    "hang_seng": ("ハンセン", "香港ハンセン", "hang seng", "hangseng"),
    "shanghai": ("上海総合", "上海", "shanghai composite"),
    "kospi": ("kospi", "コスピ"),
}

_FX_TERMS = {
    "usd_jpy": ("ドル円", "usd/jpy", "usd jpy", "usdjpy", "dollar yen"),
    "eur_usd": ("ユーロドル", "eur/usd", "eur usd", "eurusd", "euro dollar"),
    "gbp_usd": ("ポンドドル", "gbp/usd", "gbp usd", "gbpusd", "pound dollar"),
    "aud_usd": ("豪ドル米ドル", "豪ドル", "aud/usd", "aud usd", "audusd"),
    "eur_jpy": ("ユーロ円", "eur/jpy", "eur jpy", "eurjpy", "euro yen"),
    "gbp_jpy": ("ポンド円", "gbp/jpy", "gbp jpy", "gbpjpy", "pound yen"),
    "usd_chf": ("ドルスイス", "usd/chf", "usd chf", "usdchf", "dollar franc"),
    "usd_cad": ("ドルカナダ", "usd/cad", "usd cad", "usdcad", "dollar canadian"),
    "usd_cny": ("ドル人民元", "usd/cny", "usd cny", "usdcny", "dollar yuan"),
}

_BROAD_SUMMARY_TERMS = (
    "世界株価",
    "世界の株価",
    "世界市場",
    "世界の市場",
    "global market",
    "global markets",
    "world market",
    "world markets",
)

_MAJOR_FX_TERMS = (
    "主要な為替",
    "主要為替",
    "主要通貨",
    "major fx",
    "major forex",
    "major currencies",
)


def market_quote_keys(text: str) -> tuple[str, ...]:
    """Return only explicitly requested instruments; empty means a broad summary."""
    value = (text or "").strip().casefold()
    if not value:
        return ()

    selected: list[str] = []
    for key, terms in _INDEX_TERMS.items():
        if any(term.casefold() in value for term in terms):
            selected.append(key)

    major_fx = any(term.casefold() in value for term in _MAJOR_FX_TERMS)
    if major_fx and selected:
        return ()
    if major_fx:
        return tuple(_FX_TERMS)

    for key, terms in _FX_TERMS.items():
        if any(term.casefold() in value for term in terms):
            selected.append(key)

    if any(term.casefold() in value for term in _BROAD_SUMMARY_TERMS):
        return ()

    seen: set[str] = set()
    return tuple(key for key in selected if not (key in seen or seen.add(key)))

