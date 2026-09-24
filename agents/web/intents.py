"""Intent helpers for Web/Website Agent."""
from __future__ import annotations

_WEB_KEYWORDS = (
    "ホームページ",
    "ウェブサイト",
    "webサイト",
    "website",
    "サイトを作",
    "サイト制作",
    "web制作",
    "webページ",
    "ウェブページ",
    "ページを作",
    "ランディングページ",
    "lpを作",
    "html",
    "css",
    "javascript",
    "フロントエンド",
)


def is_web_intent(message: str) -> bool:
    text = str(message or "").casefold()
    return any(keyword.casefold() in text for keyword in _WEB_KEYWORDS)
