"""Provider-neutral contracts for the AI Speaker channel.

Audio providers stay outside the application core. The speaker pipeline is:
voice input -> STT -> common AIGateway -> voice output via TTS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .gateway import AIRequest, AIResponse


@dataclass(frozen=True)
class VoiceInput:
    """Audio supplied by a voice channel before speech recognition."""

    audio: bytes
    mime_type: str = "audio/wav"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceText:
    """Speech-recognition result passed to the common AI gateway."""

    text: str
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceOutput:
    """Synthesized speech returned to the voice channel."""

    audio: bytes
    mime_type: str = "audio/mpeg"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class SpeechToText(Protocol):
    def transcribe(self, request: VoiceInput) -> VoiceText:
        ...


class TextToSpeech(Protocol):
    def synthesize(self, response: AIResponse) -> VoiceOutput:
        ...


class VoicePipeline(Protocol):
    """Transport/provider-neutral voice pipeline contract."""

    def handle(self, request: VoiceInput) -> VoiceOutput:
        ...


def as_ai_request(user_id: str, speech: VoiceText, *, metadata: Mapping[str, Any] | None = None) -> AIRequest:
    """Convert recognized speech into the channel-independent gateway request."""
    merged: dict[str, Any] = dict(speech.metadata)
    if metadata:
        merged.update(metadata)
    return AIRequest(user_id=user_id, message=speech.text, channel="voice", metadata=merged)
