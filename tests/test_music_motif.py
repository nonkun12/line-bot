import pytest

from agents.music.motif import MOTIF_INTERVALS, motif_pitch


def test_motif_keeps_the_same_interval_identity_across_energy_levels():
    low = [motif_pitch("low", index) for index in range(len(MOTIF_INTERVALS))]
    medium = [motif_pitch("medium", index) for index in range(len(MOTIF_INTERVALS))]
    high = [motif_pitch("high", index) for index in range(len(MOTIF_INTERVALS))]
    assert [b - a for a, b in zip(low, low[1:])] == [
        b - a for a, b in zip(medium, medium[1:])
    ]
    assert [b - a for a, b in zip(medium, medium[1:])] == [
        b - a for a, b in zip(high, high[1:])
    ]
    assert all(m - l == 12 and h - m == 12 for l, m, h in zip(low, medium, high))


def test_motif_rejects_invalid_energy_and_note_index():
    with pytest.raises(ValueError, match="energy"):
        motif_pitch("extreme", 0)
    with pytest.raises(ValueError, match="note_index"):
        motif_pitch("low", -1)
