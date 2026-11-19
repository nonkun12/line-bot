"""Channel-neutral voice pipeline: STT -> AI Core -> TTS."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.agents import AgentRequest
from core.voice import build_speech_result, openai_transcribe_audio


@dataclass(frozen=True)
class VoicePipelineResult:
    transcript: str
    reply_text: str
    speech_provider: str = "none"
    audio_url: str | None = None
    mime_type: str | None = None

    @property
    def speech_available(self) -> bool:
        return bool(self.audio_url)


def run_voice_pipeline(
    audio: bytes,
    *,
    user_id: str,
    channel: str,
    core_handler: Callable[[AgentRequest], str],
    synthesizer=None,
    filename: str = "speech.webm",
    content_type: str | None = None,
) -> VoicePipelineResult:
    """Run speech recognition, channel-neutral Core handling, and optional TTS."""
    transcript = openai_transcribe_audio(audio, filename, content_type).strip()
    if not transcript:
        raise ValueError("voice transcription returned empty text")

    reply = str(
        core_handler(
            AgentRequest(
                user_id=str(user_id),
                message=transcript,
                channel=str(channel),
                metadata={"input": "voice_audio"},
            )
        )
        or ""
    ).strip()
    if not reply:
        raise ValueError("voice Core returned empty reply")

    speech = build_speech_result(reply, synthesizer=synthesizer)
    return VoicePipelineResult(
        transcript=transcript,
        reply_text=reply,
        speech_provider=speech.provider,
        audio_url=speech.audio_url,
        mime_type=speech.mime_type,
    )
