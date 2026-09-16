"""Mac-facing adapter boundary for the AI speaker core.

The adapter is intentionally device-neutral at this stage: microphone capture,
text-to-speech, and the AI brain are injected dependencies. This keeps the core
safe to test without requiring macOS audio permissions or hardware.
"""
from __future__ import annotations

from typing import Callable

from .ai_speaker import AISpeaker, SpeakerResponse


class MacSpeakerAdapter:
    """Connect transcription and speech playback to the AI speaker core."""

    def __init__(
        self,
        speaker: AISpeaker,
        *,
        speak: Callable[[str], None],
    ) -> None:
        self._speaker = speaker
        self._speak = speak

    def handle_transcript(self, transcript: str, *, session_id: str | None = None) -> SpeakerResponse:
        response = self._speaker.handle_transcript(transcript, session_id=session_id)
        self._speak(response.text)
        return response
