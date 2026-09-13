"""Deterministic first-pass routing for the management AI layer."""
from __future__ import annotations

from .management_contract import ManagementDecision, ManagementRequest, Specialist


_KEYWORDS: tuple[tuple[Specialist, tuple[str, ...]], ...] = (
    (Specialist.VOICE, ("音声", "喋って", "話して", "speaker", "voice")),
    (Specialist.ENGLISH, ("英語", "english", "英会話", "英文")),
    (Specialist.NEWS, ("ニュース", "news", "最新情報", "速報")),
    (Specialist.STOCKS, ("株", "株価", "stocks", "stock", "銘柄", "証券")),
)


def route(request: ManagementRequest) -> ManagementDecision:
    """Choose one specialist without invoking a model.

    The deterministic layer is intentionally conservative: first matching
    specialist wins, otherwise the request stays with General. Later model
    routing can wrap this contract without changing callers.
    """
    message = request.message.strip().casefold()
    for specialist, keywords in _KEYWORDS:
        if any(keyword.casefold() in message for keyword in keywords):
            return ManagementDecision(
                specialist=specialist,
                reason=f"matched {specialist.value} keyword",
                confidence=0.95,
                metadata={"routing": "deterministic"},
            )
    return ManagementDecision(
        specialist=Specialist.GENERAL,
        reason="no specialist keyword matched",
        confidence=0.60,
        metadata={"routing": "deterministic"},
    )
