"""Minimal Mac AI-speaker client.

Audio capture stays on the Mac. The server handles STT, AI Core routing, and
TTS. The client accepts only a fixed local recording duration and never executes
AI-generated shell commands.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx

try:
    import sounddevice as sd
except ImportError as exc:  # pragma: no cover
    sd = None
    _SOUNDDEVICE_ERROR = exc


def record_wav(path: Path, *, seconds: float, sample_rate: int = 16_000) -> None:
    if sd is None:
        raise RuntimeError(
            "sounddevice is required; install it with: python -m pip install sounddevice"
        ) from _SOUNDDEVICE_ERROR
    if not 0.5 <= seconds <= 30:
        raise ValueError("recording length must be between 0.5 and 30 seconds")
    frames = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames.tobytes())


def request_speaker(
    base_url: str, internal_key: str, user_id: str, audio_path: Path
) -> str:
    headers = {"X-Internal-Key": internal_key}
    with httpx.Client(timeout=60) as client:
        with audio_path.open("rb") as audio:
            transcription = client.post(
                f"{base_url.rstrip('/')}/api/voice/transcribe",
                headers=headers,
                files={"file": (audio_path.name, audio, "audio/wav")},
            )
        transcription.raise_for_status()
        text = transcription.json()["text"].strip()
        if not text:
            raise RuntimeError("speech recognition returned empty text")
        response = client.post(
            f"{base_url.rstrip('/')}/api/voice",
            headers=headers,
            json={"user_id": user_id, "message": text},
        )
        response.raise_for_status()
        return response.json()["reply"]


def speak_local(text: str) -> None:
    subprocess.run(["say", text], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac AI Speaker")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--base-url", default=os.environ.get("AI_SPEAKER_BASE_URL", ""))
    parser.add_argument("--user-id", default=os.environ.get("AI_SPEAKER_USER_ID", "mac-speaker"))
    args = parser.parse_args()
    internal_key = os.environ.get("INTERNAL_PUSH_KEY", "")
    if not args.base_url or not internal_key:
        raise SystemExit("AI_SPEAKER_BASE_URL and INTERNAL_PUSH_KEY are required")
    with tempfile.TemporaryDirectory(prefix="ai-speaker-") as temp_dir:
        audio_path = Path(temp_dir) / "speech.wav"
        print(f"Recording for {args.seconds:.1f}s...")
        record_wav(audio_path, seconds=args.seconds)
        reply = request_speaker(args.base_url, internal_key, args.user_id, audio_path)
    print(reply)
    speak_local(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
