"""Deterministic first-stage router for the distributed AI foundation.

Routing is intentionally local and bounded: no model call, no side effects, and
no automatic execution. The selected role is only a dispatch hint; downstream
runtime gates remain responsible for authorization, testing, review, and integration.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .multi_agent import AgentRole


@dataclass(frozen=True)
class RouteDecision:
    role: AgentRole
    reason: str


_RULES: tuple[tuple[AgentRole, tuple[str, ...]], ...] = (
    (AgentRole.VOICE, ("音声", "スピーカー", "speaker", "voice", "話して")),
    (AgentRole.ENGLISH, ("英語", "english", "英会話", "翻訳")),
    (AgentRole.STOCKS, ("株価", "株", "stocks", "stock", "ticker")),
    (AgentRole.NEWS, ("AI NEWS", "AIニュース", "ニュース", "news")),
    (AgentRole.MUSIC, ("音楽", "music", "曲", "歌")),
    (AgentRole.VIDEO, ("動画", "video", "映像")),
    (AgentRole.JOBS, ("求人", "仕事", "jobs", "job")),
    (AgentRole.MARKET, ("市場", "マーケット", "market")),
)


def route_instruction(instruction: str) -> RouteDecision:
    """Select one domain role without invoking an external model."""
    if not instruction or not instruction.strip():
        raise ValueError("instruction is required")

    normalized = re.sub(r"\s+", " ", instruction.strip()).lower()
    for role, keywords in _RULES:
        for keyword in keywords:
            if keyword.lower() in normalized:
                return RouteDecision(role, f"matched keyword: {keyword}")
    return RouteDecision(AgentRole.GENERAL, "no domain keyword matched")
