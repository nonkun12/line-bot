"""Provider-neutral management AI routing contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class Specialist(str, Enum):
    GENERAL = "general"
    VOICE = "voice"
    ENGLISH = "english"
    NEWS = "news"
    STOCKS = "stocks"


@dataclass(frozen=True)
class ManagementRequest:
    user_id: str
    message: str
    channel: str = "unknown"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.message.strip():
            raise ValueError("message is required")


@dataclass(frozen=True)
class ManagementDecision:
    specialist: Specialist
    reason: str
    confidence: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason is required")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class SpecialistBoundary:
    specialist: Specialist
    capabilities: tuple[str, ...]
    allowed_channels: tuple[str, ...] = ()


def default_specialist_boundaries() -> tuple[SpecialistBoundary, ...]:
    """Keep specialist ownership explicit before model-based routing is added."""
    return (
        SpecialistBoundary(Specialist.GENERAL, ("conversation", "fallback")),
        SpecialistBoundary(Specialist.VOICE, ("speech_to_text", "text_to_speech"), ("voice",)),
        SpecialistBoundary(Specialist.ENGLISH, ("english_learning",)),
        SpecialistBoundary(Specialist.NEWS, ("news_retrieval",)),
        SpecialistBoundary(Specialist.STOCKS, ("stock_quotes",)),
    )
