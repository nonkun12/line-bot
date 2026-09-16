"""Provider-neutral AI speaker request/response boundary.

This module intentionally handles orchestration only: audio capture and playback
remain outside the core so the same path can be used by a Mac client or another
voice frontend without coupling the runtime to a device SDK.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpeakerRequest:
    """Normalized speech request after transcription."""

    text: str
    session_id: str | None = None


@dataclass(frozen=True)
class SpeakerResponse:
    """Normalized response suitable for speech synthesis."""

    text: str
    session_id: str | None = None


class SpeakerBrain(Protocol):
    """Minimal AI Core contract used by the speaker adapter."""

    def respond(self, request: SpeakerRequest) -> SpeakerResponse:
        ...


class AISpeaker:
    """Translate a voice frontend's text into an AI Core response.

    No microphone, speaker, network, filesystem, or model-provider access occurs
    here. The boundary is deliberately small so those integrations can be tested
    independently and replaced without changing the orchestration contract.
    """

    def __init__(self, brain: SpeakerBrain) -> None:
        self._brain = brain

    def handle_transcript(self, text: str, *, session_id: str | None = None) -> SpeakerResponse:
        normalized = text.strip()
        if not normalized:
            raise ValueError("speech transcript must not be empty")
        return self._brain.respond(SpeakerRequest(normalized, session_id))
