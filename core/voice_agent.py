"""Provider-neutral AI speaker orchestration foundation.

The speaker layer keeps speech I/O separate from Core routing so LINE, a local
speaker, or another channel can reuse the same contract. It performs no I/O
itself; concrete STT/TTS adapters remain injected by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .voice import SpeechResult, SpeechSynthesizer, build_speech_result


@dataclass(frozen=True)
class VoiceInput:
    """Normalized speech input before Core processing."""

    transcript: str
    user_id: str
    channel: str = "voice"


@dataclass(frozen=True)
class VoiceResponse:
    """Normalized speaker response containing text and optional audio."""

    text: str
    speech: SpeechResult


class VoiceResponder(Protocol):
    """Injectable text responder used between STT and TTS."""

    def respond(self, request: VoiceInput) -> str:
        """Return the Core response text for normalized speech input."""


class VoiceAgent:
    """Small, deterministic STT -> Core -> TTS orchestration boundary."""

    def __init__(
        self,
        responder: VoiceResponder,
        synthesizer: SpeechSynthesizer | None = None,
    ) -> None:
        self._responder = responder
        self._synthesizer = synthesizer

    def handle(self, request: VoiceInput) -> VoiceResponse:
        transcript = str(request.transcript).strip()
        if not transcript:
            raise ValueError("transcript is required")
        user_id = str(request.user_id).strip()
        if not user_id:
            raise ValueError("user_id is required")

        normalized = VoiceInput(
            transcript=transcript,
            user_id=user_id,
            channel=str(request.channel).strip() or "voice",
        )
        text = str(self._responder.respond(normalized)).strip()
        if not text:
            raise ValueError("voice responder returned empty text")
        return VoiceResponse(text=text, speech=build_speech_result(text, self._synthesizer))


__all__ = ["VoiceAgent", "VoiceInput", "VoiceResponse", "VoiceResponder"]
