"""Shared deterministic rhythmic phrasing for MIDI and WAV composition drafts."""
from __future__ import annotations

from collections.abc import Iterator

from agents.music.motif import motif_pitch

# (beat offset, gate length in beats, accent). The four-beat phrases create
# distinct breathing patterns while preserving the same recognizable motif.
_RHYTHMS = {
    "low": ((0.0, 1.45, 0.72), (1.75, 0.8, 0.58), (3.0, 0.75, 0.68)),
    "medium": ((0.0, 0.72, 0.88), (0.75, 0.42, 0.62), (1.5, 0.72, 0.78),
               (2.5, 0.42, 0.64), (3.25, 0.55, 0.86)),
    "high": ((0.0, 0.46, 1.0), (0.5, 0.42, 0.7), (1.25, 0.22, 0.66),
             (1.5, 0.46, 0.9), (2.25, 0.42, 0.74), (3.0, 0.46, 1.0),
             (3.5, 0.42, 0.78)),
}


def melody_events(
    start_seconds: float,
    end_seconds: float,
    energy: str,
    bpm: int,
    cue_index: int = 0,
) -> Iterator[tuple[float, float, int, float]]:
    """Yield (start, end, pitch, accent) for a scene-aware melodic phrase."""
    if energy not in _RHYTHMS:
        raise ValueError("energy must be low, medium, or high")
    if bpm < 40 or bpm > 200:
        raise ValueError("bpm must be from 40 to 200")
    if end_seconds <= start_seconds:
        raise ValueError("cue end must be after cue start")
    beat_seconds = 60.0 / bpm
    bar_seconds = beat_seconds * 4.0
    phrase = _RHYTHMS[energy]
    phrase_start = start_seconds
    note_index = 0
    while phrase_start < end_seconds:
        for offset, gate, accent in phrase:
            note_start = phrase_start + offset * beat_seconds
            if note_start >= end_seconds:
                continue
            note_end = min(note_start + gate * beat_seconds, end_seconds)
            # Rotate the motif entry between scenes: same identity, fresh phrase.
            pitch = motif_pitch(energy, note_index + cue_index * 3)
            yield note_start, note_end, pitch, accent
            note_index += 1
        phrase_start += bar_seconds


__all__ = ["melody_events"]
