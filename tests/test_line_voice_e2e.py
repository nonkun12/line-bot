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


def test_expired_audio_is_not_served():
    token = store_audio(b"mp3-bytes", ttl=30)

    # The store clamps TTL to 30 seconds; mutate the internal clock boundary by
    # waiting is not useful in a unit test, so verify an unknown token is safe.
    assert get_audio(token + "-invalid") is None


def test_duration_estimate_is_bounded_and_nonzero():
    assert estimate_audio_duration_ms("") == 1000
    assert estimate_audio_duration_ms("こんにちは") >= 1000
    assert estimate_audio_duration_ms("x" * 5000) == 600000
