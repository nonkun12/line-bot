"""Shared original musical motif used by MIDI and PCM renderers.

The motif is deliberately diatonic and remains recognizable across scene
energy changes. Energy changes register and dynamics, not the motif identity.
"""
from __future__ import annotations

MOTIF_INTERVALS = (0, 2, 4, 7, 5, 4, 2, 0)
ENERGY_OCTAVE = {"low": -12, "medium": 0, "high": 12}


def motif_pitch(energy: str, note_index: int, *, base_pitch: int = 72) -> int:
    if energy not in ENERGY_OCTAVE:
        raise ValueError("energy must be low, medium, or high")
    if type(note_index) is not int or note_index < 0:
        raise ValueError("note_index must be a non-negative integer")
    pitch = base_pitch + ENERGY_OCTAVE[energy] + MOTIF_INTERVALS[note_index % len(MOTIF_INTERVALS)]
    if not 0 <= pitch <= 127:
        raise ValueError("motif pitch falls outside the MIDI note range")
    return pitch


__all__ = ["MOTIF_INTERVALS", "ENERGY_OCTAVE", "motif_pitch"]
