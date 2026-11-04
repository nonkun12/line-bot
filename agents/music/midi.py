"""Dependency-free Standard MIDI File generation for original audiovisual cues.

The generated file is a compact piano sketch, not a rendered audio recording.
It uses only Python's standard library so local/cloud execution stays free.
"""
from __future__ import annotations

import base64
import struct
from typing import Any

_TICKS_PER_QUARTER = 480
_BPM = 96
_TICKS_PER_SECOND = _TICKS_PER_QUARTER * _BPM / 60
_MOTIF = (60, 64, 67, 72, 71, 67, 64, 62)
_CHORDS = ((48, 52, 55), (43, 47, 50), (45, 48, 52), (41, 45, 48))
_ENERGY_NOTES = {"low": 2, "medium": 4, "high": 8}


def _vlq(value: int) -> bytes:
    """Encode a non-negative MIDI variable-length quantity."""
    if value < 0:
        raise ValueError("MIDI delta time cannot be negative")
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
        value >>= 7
    encoded = bytearray()
    while True:
        encoded.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            return bytes(encoded)


def _tick(seconds: int | float) -> int:
    return round(float(seconds) * _TICKS_PER_SECOND)


def build_midi_bytes(music_plan: dict[str, Any]) -> bytes:
    """Render a validated cue plan to a single-track type-0 MIDI byte string."""
    if not isinstance(music_plan, dict):
        raise ValueError("music_plan must be an object")
    cues = music_plan.get("cues")
    duration = music_plan.get("duration_seconds")
    if type(duration) is not int or duration <= 0 or not isinstance(cues, list) or not cues:
        raise ValueError("music plan requires positive duration and non-empty cues")

    events: list[tuple[int, int, bytes]] = []
    # 96 BPM, 4/4, acoustic grand piano.
    events.append((0, 0, b"\xff\x51\x03" + (60_000_000 // _BPM).to_bytes(3, "big")))
    events.append((0, 1, b"\xff\x58\x04\x04\x02\x18\x08"))
    events.append((0, 2, b"\xc0\x00"))

    previous_end = 0
    for cue_index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("each music cue must be an object")
        start = cue.get("start_seconds")
        end = cue.get("end_seconds")
        energy = cue.get("energy")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or start < previous_end or end <= start or end > duration
            or energy not in _ENERGY_NOTES
        ):
            raise ValueError(f"invalid timing or energy in cue {cue_index + 1}")
        if cue.get("scene_id") is None:
            raise ValueError(f"scene_id missing in cue {cue_index + 1}")
        previous_end = end
        start_tick, end_tick = _tick(start), _tick(end)
        span = end_tick - start_tick
        if span < 2:
            raise ValueError("cue is too short to contain a MIDI note")

        chord = _CHORDS[cue_index % len(_CHORDS)]
        velocity = {"low": 42, "medium": 62, "high": 82}[energy]
        # Sustained harmony establishes the scene's emotional bed.
        for note in chord:
            events.append((start_tick, 4, bytes((0x90, note, max(1, velocity - 18)))))
            events.append((end_tick, 3, bytes((0x80, note, 0))))

        count = _ENERGY_NOTES[energy]
        for step in range(count):
            note_start = start_tick + (span * step // count)
            note_end = start_tick + (span * (step + 1) // count)
            if note_end <= note_start:
                continue
            motif_note = _MOTIF[(cue_index * 2 + step) % len(_MOTIF)]
            # A little register lift at the climax, while retaining the motif.
            if energy == "high":
                motif_note += 12
            note_velocity = min(120, velocity + (5 if step in (0, count - 1) else 0))
            events.append((note_start, 5, bytes((0x90, motif_note, note_velocity))))
            events.append((note_end, 2, bytes((0x80, motif_note, 0))))

    events.sort(key=lambda item: (item[0], item[1]))
    track = bytearray()
    last_tick = 0
    for tick, _priority, payload in events:
        track.extend(_vlq(tick - last_tick))
        track.extend(payload)
        last_tick = tick
    track.extend(b"\x00\xff\x2f\x00")
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, _TICKS_PER_QUARTER)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def build_midi_artifact(music_plan: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe base64 MIDI artifact for a LINE/API response."""
    midi = build_midi_bytes(music_plan)
    title = str(music_plan.get("source_scenario_title") or "audiovisual-score")
    safe_title = "".join(ch for ch in title if ch.isalnum() or ch in "-_")[:40] or "audiovisual-score"
    return {
        "filename": f"{safe_title}.mid",
        "mime_type": "audio/midi",
        "encoding": "base64",
        "content_base64": base64.b64encode(midi).decode("ascii"),
        "size_bytes": len(midi),
        "duration_seconds": music_plan["duration_seconds"],
        "status": "generated_midi_sketch",
        "limitations": "MIDI演奏データです。音声ファイルではなく、再生にはMIDI音源が必要です。",
    }


__all__ = ["build_midi_bytes", "build_midi_artifact"]
