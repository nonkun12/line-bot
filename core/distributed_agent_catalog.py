"""Canonical catalog for the distributed specialist AI surface.

The catalog is metadata only. It does not create providers or grant capabilities.
Execution remains subject to the existing specialist gate and executor registry.
"""
from __future__ import annotations

from dataclasses import dataclass

from .multi_agent import AgentRole


@dataclass(frozen=True)
class DistributedAgentDescriptor:
    role: AgentRole
    key: str
    agent_name: str
    label: str
    icon: str
    detail: str
    capability: str


DISTRIBUTED_AGENT_CATALOG: tuple[DistributedAgentDescriptor, ...] = (
    DistributedAgentDescriptor(
        AgentRole.GENERAL, "general", "normal", "General AI", "🧩",
        "汎用会話・フォールバック", "conversation",
    ),
    DistributedAgentDescriptor(
        AgentRole.VOICE, "voice", "voice", "AIスピーカー / Voice", "🎙️",
        "voice API available", "text_to_speech",
    ),
    DistributedAgentDescriptor(
        AgentRole.ENGLISH, "english_learning", "english_learning", "英語学習AI", "🇬🇧",
        "MVP: lesson / vocabulary / grammar / conversation / quiz / review", "english_learning",
    ),
    DistributedAgentDescriptor(
        AgentRole.NEWS, "ai_news", "ai_news", "AI NEWS", "📰",
        "Google News RSS headline retrieval", "news_retrieval",
    ),
    DistributedAgentDescriptor(
        AgentRole.STOCKS, "stocks", "stocks", "株価AI", "📈",
        "Yahoo Finance + テクニカル分析・比較・監視銘柄", "stock_quotes",
    ),
    DistributedAgentDescriptor(
        AgentRole.MARKET, "global_market", "global_market", "世界市場AI", "🌎",
        "主要株価指数（NYダウ・S&P500・NASDAQ・日経225・DAX・FTSE100・香港ハンセン・上海総合・KOSPI） + 主要為替", "market_summary",
    ),
    DistributedAgentDescriptor(
        AgentRole.JOBS, "jobs", "job_seeking", "求職AI", "💼",
        "求人検索・応募準備・面接支援。実求人サイト連携は未接続", "job_search",
    ),
    DistributedAgentDescriptor(
        AgentRole.MUSIC, "music", "music", "音楽AI", "🎵",
        "選曲・作曲/作詞補助・プレイリスト設計。音源生成・再生は未接続", "music_planning",
    ),
    DistributedAgentDescriptor(
        AgentRole.VIDEO, "video", "video", "映像AI", "🎬",
        "動画企画・台本・絵コンテ・編集設計。動画生成・書き出しは未接続", "video_planning",
    ),
)


def descriptor_for_role(role: AgentRole) -> DistributedAgentDescriptor | None:
    if not isinstance(role, AgentRole):
        return None
    return next((item for item in DISTRIBUTED_AGENT_CATALOG if item.role is role), None)


def descriptor_for_key(key: str) -> DistributedAgentDescriptor | None:
    normalized = str(key).strip().casefold()
    return next((item for item in DISTRIBUTED_AGENT_CATALOG if item.key == normalized), None)


__all__ = [
    "DISTRIBUTED_AGENT_CATALOG",
    "DistributedAgentDescriptor",
    "descriptor_for_key",
    "descriptor_for_role",
]
