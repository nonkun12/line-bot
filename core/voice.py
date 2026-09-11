"""Channel-neutral voice output capability contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
