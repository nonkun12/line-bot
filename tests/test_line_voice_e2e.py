from __future__ import annotations

import time

from core.line_voice import estimate_audio_duration_ms, get_audio, store_audio


def test_store_audio_returns_short_lived_token():
    token = store_audio(b"mp3-bytes", ttl=30)

    item = get_audio(token)

    assert item is not None
    assert item.data == b"mp3-bytes"
    assert item.mime_type == "audio/mpeg"
    assert item.expires_at > time.time()


def test_unknown_audio_token_is_not_served():
    assert get_audio("definitely-not-a-real-token") is None


def test_duration_estimate_is_bounded_and_nonzero():
    assert estimate_audio_duration_ms("") == 1000
    assert estimate_audio_duration_ms("こんにちは") >= 1000
    assert estimate_audio_duration_ms("x" * 5000) == 600000
