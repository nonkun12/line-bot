""""Deterministic first-pass routing for the management AI layer."""
from __future__ import annotations

from .management_contract import ManagementDecision, ManagementRequest, Specialist


_KEYWORDS: tuple[tuple[Specialist, tuple[str, ...]], ...] = (
    (Specialist.VOICE, ("音声", "喋って", "話して", "speaker", "voice")),
    (Specialist.JOBS, ("求職", "転職", "就職", "求人", "仕事探し", "応募", "履歴書", "職務経歴書", "志望動機", "面接", "career", "resume", "cv", "job")),
    (Specialist.ENGLISH, ("英語", "english", "英会話", "英文")),
    (Specialist.NEWS, ("ニュース", "news", "最新情報", "速報")),
    (Specialist.STOCKS, ("株", "株価", "stocks", "stock", "銘柄", "証券")),
)


def route(request: ManagementRequest) -> ManagementDecision:
    """Choose one specialist without invoking a model.

    The deterministic layer is intentionally conservative: first matching
    specialist wins, otherwise the request stays with General. Request
    metadata and channel are preserved in the decision so downstream agents
    remain channel-independent.
    """
    message = request.message.strip().casefold()
    routing_metadata = {
        "routing": "deterministic",
        "channel": request.channel,
        "request_metadata": dict(request.metadata),
    }
    for specialist, keywords in _KEYWORDS:
        if any(keyword.casefold() in message for keyword in keywords):
            return ManagementDecision(
                specialist=specialist,
                reason=f"matched {specialist.value} keyword",
                confidence=0.95,
                metadata=routing_metadata,
            )
    return ManagementDecision(
        specialist=Specialist.GENERAL,
        reason="no specialist keyword matched",
        confidence=0.60,
        metadata=routing_metadata,
    )
