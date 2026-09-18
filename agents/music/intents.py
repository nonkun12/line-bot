"""Intent helpers for Music AI."""
from __future__ import annotations

_MUSIC_KEYWORDS = (
    "音楽", "music", "曲", "歌", "作曲", "作詞", "bgm", "プレイリスト",
    "playlist", "メロディ", "楽曲",
)


def is_music_intent(message: str) -> bool:
    text = str(message or "").casefold()
    return any(keyword.casefold() in text for keyword in _MUSIC_KEYWORDS)
