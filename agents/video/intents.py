"""Intent helpers for Video AI."""
from __future__ import annotations

_VIDEO_KEYWORDS = (
    "動画", "映像", "video", "movie", "ショート動画", "youtube",
    "ユーチューブ", "編集", "絵コンテ", "台本", "シナリオ", "脚本", "scenario", "動画制作",
)


def is_video_intent(message: str) -> bool:
    text = str(message or "").casefold()
    return any(keyword.casefold() in text for keyword in _VIDEO_KEYWORDS)


def is_video_scenario_request(message: str) -> bool:
    """Identify scenario/script requests that require ordered Video→Music work."""
    normalized = str(message or "").casefold()
    return is_video_intent(message) and any(
        keyword in normalized for keyword in ("シナリオ", "台本", "脚本", "script", "scenario")
    )


__all__ = ["is_video_intent", "is_video_scenario_request"]
