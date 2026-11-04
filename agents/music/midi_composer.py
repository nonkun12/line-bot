"""Original, deterministic MIDI sketch generation using only the Python standard library.

The module converts a validated scenario-aware music plan into an editable
Standard MIDI File. It creates a new motif; it does not copy or sample existing
recordings. Audio rendering remains a separate local-tool step.
"""
from __future__ import annotations

from pathlib import Path

from agents.music.motif import motif_pitch
from typing import Any


_TICKS_PER_BEAT = 480
_SECONDS_PER_BEAT_AT_120 = 0.5
_CHORDS = (
    (60, (60, 64, 67)),
    (65, (65, 69, 72)),
    (57, (57, 60, 64)),
    (67, (67, 71, 74)),
)


def _vlq(value: int) -> bytes:
    if type(value) is not int or value < 0:
        raise ValueError("MIDI delta time must be a non-negative integer")
    buffer = value & 0x7F
    value >>= 7
    encoded = bytearray()
    while value:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
        value >>= 7
    while True:
        encoded.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(encoded)


def _track(events: list[tuple[int, int, bytes]]) -> bytes:
    events.sort(key=lambda event: (event[0], event[1]))
    payload = bytearray()
    previous_tick = 0
    for tick, _priority, message in events:
        if tick < previous_tick:
            raise ValueError("MIDI events must be chronological")
        payload.extend(_vlq(tick - previous_tick))
        payload.extend(message)
        previous_tick = tick
    payload.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + len(payload).to_bytes(4, "big") + bytes(payload)


def _note(events: list[tuple[int, int, bytes]], channel: int, pitch: int, start: int, end: int, velocity: int) -> None:
    if not 0 <= pitch <= 127 or start < 0 or end <= start or not 1 <= velocity <= 127:
        raise ValueError("MIDI note is outside the supported range")
    events.append((start, 1, bytes((0x90 | channel, pitch, velocity))))
    events.append((end, 0, bytes((0x80 | channel, pitch, 0))))


def build_midi_bytes(music_plan: dict[str, Any], *, bpm: int = 120) -> bytes:
    """Return a four-track MIDI composition sketch from a validated music plan."""
    if not isinstance(music_plan, dict) or music_plan.get("schema_version") != "video-music-plan.v1":
        raise ValueError("music_plan must use video-music-plan.v1")
    duration = music_plan.get("duration_seconds")
    cues = music_plan.get("cues")
    if type(duration) is not int or not 1 <= duration <= 3600:
        raise ValueError("duration_seconds must be an integer from 1 to 3600")
    if type(bpm) is not int or not 40 <= bpm <= 200:
        raise ValueError("bpm must be an integer from 40 to 200")
    if not isinstance(cues, list) or not cues or len(cues) > 100:
        raise ValueError("music plan must contain 1 to 100 cues")

    seconds_to_ticks = lambda seconds: round(seconds * bpm / 60 * _TICKS_PER_BEAT)
    melody_events: list[tuple[int, int, bytes]] = [(0, 0, bytes((0xC0, 48)))]
    harmony_events: list[tuple[int, int, bytes]] = [(0, 0, bytes((0xC1, 0)))]
    bass_events: list[tuple[int, int, bytes]] = [(0, 0, bytes((0xC2, 32)))]
    last_end = 0

    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("each cue must be an object")
        start = cue.get("start_seconds")
        end = cue.get("end_seconds")
        energy = cue.get("energy")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or start < 0 or end <= start or end > duration
            or start < last_end
            or energy not in {"low", "medium", "high"}
        ):
            raise ValueError(f"cue {index + 1} has invalid timing or energy")
        last_end = end
        start_tick = seconds_to_ticks(start)
        end_tick = seconds_to_ticks(end)
        bar_ticks = _TICKS_PER_BEAT * 4
        beat_ticks = _TICKS_PER_BEAT
        chord_root, chord_notes = _CHORDS[index % len(_CHORDS)]
        velocity = {"low": 48, "medium": 68, "high": 88}[energy]
        bar_start = (start_tick // bar_ticks) * bar_ticks

        # Sustain a simple original harmonic bed over this cue.
        while bar_start < end_tick:
            chord_end = min(bar_start + bar_ticks, end_tick)
            if chord_end > max(bar_start, start_tick):
                chord_start = max(bar_start, start_tick)
                for pitch in chord_notes:
                    _note(harmony_events, 1, pitch, chord_start, chord_end, max(35, velocity - 15))
                _note(bass_events, 2, chord_root - 24, chord_start, chord_end, max(30, velocity - 5))
            bar_start += bar_ticks

        intervals = _MELODY_INTERVALS[energy]
        step = beat_ticks // 2
        cursor = start_tick
        note_index = 0
        while cursor < end_tick:
            pitch = motif_pitch(energy, note_index)
            note_end = min(cursor + int(step * 0.82), end_tick)
            _note(melody_events, 0, pitch, cursor, note_end, velocity)
            cursor += step
            note_index += 1

    tempo_us = round(60_000_000 / bpm)
    conductor = _track([
        (0, 0, b"\xff\x51\x03" + tempo_us.to_bytes(3, "big")),
        (0, 0, b"\xff\x58\x04\x04\x02\x18\x08"),
        (0, 0, b"\xff\x59\x02\x00\x00"),
    ])
    tracks = [
        conductor,
        _track(melody_events),
        _track(harmony_events),
        _track(bass_events),
    ]
    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + len(tracks).to_bytes(2, "big") + _TICKS_PER_BEAT.to_bytes(2, "big")
    return header + b"".join(tracks)


def write_midi_file(music_plan: dict[str, Any], output_path: str | Path, *, bpm: int = 120) -> dict[str, Any]:
    """Write a new MIDI file without overwriting an existing artifact."""
    path = Path(output_path)
    data = build_midi_bytes(music_plan, bpm=bpm)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return {
        "path": str(path),
        "format": "Standard MIDI File type 1",
        "tracks": 4,
        "bpm": bpm,
        "bytes": len(data),
        "status": "generated",
    }


__all__ = ["build_midi_bytes", "write_midi_file"]
