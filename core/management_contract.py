"""Provider-neutral management AI routing contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


_MAX_USER_ID_CHARS = 200
_MAX_MESSAGE_CHARS = 4000
_MAX_CHANNEL_CHARS = 100
_MAX_METADATA_ITEMS = 16
_MAX_METADATA_KEY_CHARS = 100
_MAX_METADATA_VALUE_CHARS = 1000
_MAX_REASON_CHARS = 500


class Specialist(str, Enum):
    GENERAL = "general"
    VOICE = "voice"
    ENGLISH = "english"
    NEWS = "news"
    STOCKS = "stocks"
    MARKET = "market"
    JOBS = "jobs"
    MUSIC = "music"
    VIDEO = "video"
    WEB = "web"


@dataclass(frozen=True)
class ManagementRequest:
    user_id: str
    message: str
    channel: str = "unknown"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id is required")
        if len(self.user_id) > _MAX_USER_ID_CHARS:
            raise ValueError("user_id exceeds maximum length")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message is required")
        if len(self.message) > _MAX_MESSAGE_CHARS:
            raise ValueError("message exceeds maximum length")
        if not isinstance(self.channel, str) or not self.channel.strip():
            raise ValueError("channel is required")
        if len(self.channel) > _MAX_CHANNEL_CHARS:
            raise ValueError("channel exceeds maximum length")
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class ManagementDecision:
    specialist: Specialist
    reason: str
    confidence: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.specialist, Specialist):
            raise ValueError("specialist must be a Specialist")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason is required")
        if len(self.reason) > _MAX_REASON_CHARS:
            raise ValueError("reason exceeds maximum length")
        if self.confidence is not None and not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric")
        if isinstance(self.confidence, bool):
            raise ValueError("confidence must be numeric")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class SpecialistBoundary:
    specialist: Specialist
    capabilities: tuple[str, ...]
    allowed_channels: tuple[str, ...] = ()


def _validate_metadata(metadata: Mapping[str, object]) -> None:
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    if len(metadata) > _MAX_METADATA_ITEMS:
        raise ValueError("metadata contains too many items")
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > _MAX_METADATA_KEY_CHARS
        ):
            raise ValueError("metadata key exceeds bounded contract")
        if len(str(value)) > _MAX_METADATA_VALUE_CHARS:
            raise ValueError("metadata value exceeds bounded contract")


def default_specialist_boundaries() -> tuple[SpecialistBoundary, ...]:
    """Keep specialist ownership explicit before model-based routing is added."""
    return (
        SpecialistBoundary(Specialist.GENERAL, ("conversation", "fallback")),
        SpecialistBoundary(Specialist.VOICE, ("speech_to_text", "text_to_speech"), ("voice",)),
        SpecialistBoundary(Specialist.ENGLISH, ("english_learning",)),
        SpecialistBoundary(Specialist.NEWS, ("news_retrieval",)),
        SpecialistBoundary(Specialist.STOCKS, ("stock_quotes",)),
        SpecialistBoundary(Specialist.MARKET, ("global_market", "fx", "market_summary")),
        SpecialistBoundary(
            Specialist.JOBS,
            ("job_search", "resume", "career_history", "application", "interview"),
        ),
        SpecialistBoundary(Specialist.MUSIC, ("music_planning", "composition", "playlist")),
        SpecialistBoundary(Specialist.VIDEO, ("video_planning", "script", "storyboard", "editing")),
        SpecialistBoundary(Specialist.WEB, ("web_planning", "website_generation", "frontend", "static_site")),
    )


_SPECIALIST_BOUNDARIES = default_specialist_boundaries()


def specialist_boundary(specialist: Specialist) -> SpecialistBoundary:
    """Return the immutable capability boundary for one specialist."""
    return next(item for item in _SPECIALIST_BOUNDARIES if item.specialist is specialist)
