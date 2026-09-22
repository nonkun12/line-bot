"""Deterministic first-pass routing for the management AI layer."""
from __future__ import annotations

from .management_contract import ManagementDecision, ManagementRequest, Specialist


_KEYWORDS: tuple[tuple[Specialist, tuple[str, ...]], ...] = (
    (Specialist.VOICE, ("音声", "喋って", "話して", "speaker", "voice")),
    (Specialist.ENGLISH, ("英語", "english", "英会話", "英文")),
    (Specialist.NEWS, ("ニュース", "news", "最新情報", "速報")),
    (Specialist.MARKET, ("NYダウ", "ダウ平均", "世界株価", "世界の株価", "為替", "ドル円", "forex", "fx", "exchange rate", "currency")),
    (Specialist.STOCKS, ("株", "株価", "stocks", "stock", "銘柄", "証券")),
    (Specialist.JOBS, ("求職", "転職", "就職", "求人", "仕事探し", "仕事を探", "採用", "応募", "履歴書", "職務経歴書", "志望動機", "面接", "キャリア", "job", "jobs", "career", "resume", "cv", "interview", "application")),
    (Specialist.MUSIC, ("音楽", "music", "作曲", "作詞", "playlist", "プレイリスト", "BGM", "楽曲")),
    (Specialist.VIDEO, ("動画", "映像", "video", "movie", "絵コンテ", "動画制作", "ショート動画")),
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
    matches = [
        specialist
        for specialist, keywords in _KEYWORDS
        if any(keyword.casefold() in message for keyword in keywords)
    ]
    routing_metadata["matched_specialists"] = [specialist.value for specialist in matches]
    routing_metadata["routing_priority"] = (
        [specialist.value for specialist, _ in _KEYWORDS].index(matches[0].value) + 1
        if matches
        else None
    )
    if matches:
        specialist = matches[0]
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
