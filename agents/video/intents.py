"""Intent helpers for Video AI."""
from __future__ import annotations

_VIDEO_KEYWORDS = (
    "動画", "映像", "video", "movie", "ショート動画", "youtube",
    "ユーチューブ", "編集", "絵コンテ", "台本", "動画制作",
)


def is_video_intent(message: str) -> bool:
    text = str(message or "").casefold()
    return any(keyword.casefold() in text for keyword in _VIDEO_KEYWORDS)
