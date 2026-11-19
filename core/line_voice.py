"""Small in-process store for short-lived LINE audio replies."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredAudio:
    data: bytes
    mime_type: str
    expires_at: float


_LOCK = threading.Lock()
_STORE: dict[str, StoredAudio] = {}
_MAX_ITEMS = 32
_DEFAULT_TTL = 300


def _purge(now: float) -> None:
    expired = [token for token, item in _STORE.items() if item.expires_at <= now]
    for token in expired:
        _STORE.pop(token, None)


def store_audio(data: bytes, mime_type: str = "audio/mpeg", ttl: int = _DEFAULT_TTL) -> str:
    if not data:
        raise ValueError("audio data is empty")
    ttl = max(30, min(int(ttl), 600))
    now = time.time()
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _purge(now)
        while len(_STORE) >= _MAX_ITEMS:
            oldest = min(_STORE, key=lambda key: _STORE[key].expires_at)
            _STORE.pop(oldest, None)
        _STORE[token] = StoredAudio(
            data=bytes(data),
            mime_type=mime_type or "audio/mpeg",
            expires_at=now + ttl,
        )
    return token


def get_audio(token: str) -> StoredAudio | None:
    if not token:
        return None
    now = time.time()
    with _LOCK:
        _purge(now)
        return _STORE.get(token)


def estimate_audio_duration_ms(text: str) -> int:
    """Conservative duration estimate used by LINE's required audio field."""
    # Japanese speech is roughly 4-6 mora/characters per second; this is only
    # metadata for the LINE audio bubble, not an audio decoder.
    chars = max(1, len((text or "").strip()))
    duration = int(chars / 5.0 * 1000)
    return max(1000, min(duration, 600000))
