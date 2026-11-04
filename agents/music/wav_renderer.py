"""Dependency-free PCM rendering for original audiovisual music sketches.

This is a simple synthesized reference render, not a sample-library instrument
or a substitute for final mixing with a free soundfont in a DAW.
"""
from __future__ import annotations

import math
import struct
import wave
from array import array
from pathlib import Path

from agents.music.motif import motif_pitch
from typing import Any


_SAMPLE_RATE = 22050
_MAX_RENDER_SECONDS = 90
_CHORDS = (
    (60, (60, 64, 67)),
    (65, (65, 69, 72)),
    (57, (57, 60, 64)),
    (67, (67, 71, 74)),
)


def _frequency(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def _events(music_plan: dict[str, Any], bpm: int) -> list[tuple[float, float, int, float, float]]:
    events = []
    beat = 60.0 / bpm
    for index, cue in enumerate(music_plan["cues"]):
        start = float(cue["start_seconds"])
        end = float(cue["end_seconds"])
        energy = cue["energy"]
        velocity = {"low": 0.24, "medium": 0.34, "high": 0.43}[energy]
        chord_root, chord_notes = _CHORDS[index % len(_CHORDS)]
        # Melody: syncopation is deliberately restrained for a first draft.
        step = beat / 2.0
        cursor = start
        note_index = 0
        while cursor < end:
            note_end = min(cursor + step * 0.78, end)
            pitch = motif_pitch(energy, note_index)
            events.append((cursor, note_end, pitch, velocity, 0.0))
            cursor += step
            note_index += 1
        # Sustained triad and bass anchor provide a simple harmonic foundation.
        events.append((start, end, chord_root - 24, velocity * 0.42, 0.0))
        for voice, pitch in enumerate(chord_notes):
            pan = (-0.22, 0.0, 0.22)[voice]
            events.append((start, end, pitch, velocity * 0.28, pan))
    return events


def build_wav_bytes(
    music_plan: dict[str, Any],
    *,
    bpm: int = 120,
    sample_rate: int = _SAMPLE_RATE,
) -> bytes:
    """Render a short original cue plan to 16-bit PCM WAV."""
    if not isinstance(music_plan, dict) or music_plan.get("schema_version") != "video-music-plan.v1":
        raise ValueError("music_plan must use video-music-plan.v1")
    duration = music_plan.get("duration_seconds")
    cues = music_plan.get("cues")
    if type(duration) is not int or not 1 <= duration <= _MAX_RENDER_SECONDS:
        raise ValueError(f"duration_seconds must be an integer from 1 to {_MAX_RENDER_SECONDS}")
    if type(bpm) is not int or not 40 <= bpm <= 200:
        raise ValueError("bpm must be an integer from 40 to 200")
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 48000:
        raise ValueError("sample_rate must be an integer from 8000 to 48000")
    if not isinstance(cues, list) or not cues or len(cues) > 100:
        raise ValueError("music plan must contain 1 to 100 cues")

    previous_end = 0.0
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("each cue must be an object")
        start, end, energy = cue.get("start_seconds"), cue.get("end_seconds"), cue.get("energy")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or start < previous_end or end <= start or end > duration
            or energy not in {"low", "medium", "high"}
        ):
            raise ValueError(f"cue {index + 1} has invalid timing or energy")
        previous_end = float(end)

    total_frames = duration * sample_rate
    left_mix = array("f", [0.0]) * total_frames
    right_mix = array("f", [0.0]) * total_frames
    for start, end, pitch, amplitude, pan in _events(music_plan, bpm):
        first = max(0, int(start * sample_rate))
        last = min(total_frames, int(end * sample_rate))
        if last <= first:
            continue
        frequency = _frequency(pitch)
        phase_step = 2.0 * math.pi * frequency / sample_rate
        attack = min(0.025, (end - start) * 0.2)
        release = min(0.12, (end - start) * 0.35)
        left_gain = math.sqrt((1.0 - pan) / 2.0)
        right_gain = math.sqrt((1.0 + pan) / 2.0)
        for frame in range(first, last):
            elapsed = frame / sample_rate - start
            remaining = end - frame / sample_rate
            envelope = min(1.0, elapsed / max(attack, 0.001), remaining / max(release, 0.001))
            phase = phase_step * (frame - first)
            # A fundamental plus a quiet second harmonic gives a soft synthetic tone.
            sample = math.sin(phase) * 0.82 + math.sin(phase * 2.0) * 0.18
            value = sample * amplitude * envelope
            left_mix[frame] += value * left_gain
            right_mix[frame] += value * right_gain

    pcm = bytearray(total_frames * 4)
    for index, (left, right) in enumerate(zip(left_mix, right_mix)):
        # Keep conservative headroom; final mastering is a separate stage.
        left_sample = max(-0.92, min(0.92, left * 0.62))
        right_sample = max(-0.92, min(0.92, right * 0.62))
        struct.pack_into("<hh", pcm, index * 4, int(left_sample * 32767), int(right_sample * 32767))
    output = bytearray()
    import io
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    output.extend(buffer.getvalue())
    return bytes(output)


def write_wav_file(
    music_plan: dict[str, Any],
    output_path: str | Path,
    *,
    bpm: int = 120,
    sample_rate: int = _SAMPLE_RATE,
) -> dict[str, Any]:
    """Write a new WAV file without overwriting an existing artifact."""
    path = Path(output_path)
    data = build_wav_bytes(music_plan, bpm=bpm, sample_rate=sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return {
        "path": str(path),
        "format": "WAV PCM 16-bit stereo",
        "sample_rate": sample_rate,
        "duration_seconds": music_plan["duration_seconds"],
        "bytes": len(data),
        "status": "generated",
    }


__all__ = ["build_wav_bytes", "write_wav_file"]
