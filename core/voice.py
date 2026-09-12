"""Channel-neutral voice contracts and optional OpenAI audio adapters."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class SpeechResult:
    """Normalized result returned by a speech synthesizer."""

    text: str
    audio_url: str | None = None
    mime_type: str | None = None
    provider: str = "none"

    @property
    def available(self) -> bool:
        return bool(self.audio_url)


class SpeechSynthesizer(Protocol):
    """Provider-neutral contract for optional text-to-speech backends."""

    name: str

    def synthesize(self, text: str) -> SpeechResult:
        """Synthesize text and return a normalized result."""


class DisabledSpeechSynthesizer:
    """Safe default when no TTS backend is configured."""

    name = "none"

    def synthesize(self, text: str) -> SpeechResult:
        return SpeechResult(text=text, provider=self.name)


def build_speech_result(text: str, synthesizer: SpeechSynthesizer | None = None) -> SpeechResult:
    """Use the configured synthesizer, falling back safely to text-only mode."""
    backend = synthesizer or DisabledSpeechSynthesizer()
    try:
        result = backend.synthesize(text)
    except Exception:
        return SpeechResult(text=text, provider="none")

    if not isinstance(result, SpeechResult):
        return SpeechResult(text=text, provider="none")
    return result


_OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio"
_MAX_TTS_CHARS = 4096
_DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
_DEFAULT_TTS_VOICE = "alloy"
_DEFAULT_STT_MODEL = "whisper-1"


def openai_tts_audio(text: str) -> tuple[bytes, str]:
    """Generate MP3 speech through OpenAI's Audio Speech endpoint.

    The API key is read only from the environment and is never returned to callers.
    """
    clean = str(text).strip()
    if not clean:
        raise ValueError("text is required")
    if len(clean) > _MAX_TTS_CHARS:
        raise ValueError("text exceeds maximum speech length")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = os.environ.get("VOICE_TTS_MODEL", _DEFAULT_TTS_MODEL).strip() or _DEFAULT_TTS_MODEL
    voice = os.environ.get("VOICE_TTS_VOICE", _DEFAULT_TTS_VOICE).strip() or _DEFAULT_TTS_VOICE
    timeout = float(os.environ.get("VOICE_TTS_TIMEOUT", "30"))

    response = httpx.post(
        f"{_OPENAI_AUDIO_URL}/speech",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "voice": voice,
            "input": clean,
            "response_format": "mp3",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content, "audio/mpeg"


def openai_transcribe_audio(audio: bytes, filename: str, content_type: str | None = None) -> str:
    """Transcribe an uploaded audio clip through OpenAI's transcription endpoint."""
    if not audio:
        raise ValueError("audio is required")
    safe_filename = os.path.basename(filename or "speech.webm") or "speech.webm"
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = os.environ.get("VOICE_STT_MODEL", _DEFAULT_STT_MODEL).strip() or _DEFAULT_STT_MODEL
    timeout = float(os.environ.get("VOICE_STT_TIMEOUT", "60"))
    files = {"file": (safe_filename, audio, content_type or "application/octet-stream")}
    data = {"model": model, "response_format": "json"}

    response = httpx.post(
        f"{_OPENAI_AUDIO_URL}/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files=files,
        data=data,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise RuntimeError("transcription returned no text")
    return text
