from __future__ import annotations

import io
import wave

from agents.music.expression import melody_events
from agents.music.midi_composer import build_midi_bytes
from agents.music.score_plan import build_music_plan
from agents.music.wav_renderer import build_wav_bytes
from agents.video.scenario import build_scenario


def _plan() -> dict:
    scenario = build_scenario(
        "夜明けに向かう小さな旅",
        duration_seconds=24,
        scene_count=4,
    )
    return build_music_plan(scenario)


def test_scene_energy_changes_rhythm_density_and_phrase() -> None:
    low = list(melody_events(0, 8, "low", 120, 0))
    medium = list(melody_events(0, 8, "medium", 120, 1))
    high = list(melody_events(0, 8, "high", 120, 2))

    assert len(low) < len(medium) < len(high)
    assert len({event[2] for event in low}) > 1
    assert low != medium
    assert medium != high


def test_midi_and_wav_render_scene_aware_plan() -> None:
    plan = _plan()

    midi = build_midi_bytes(plan)
    assert midi.startswith(b"MThd")
    assert int.from_bytes(midi[10:12], "big") == 4

    wav_bytes = build_wav_bytes(plan)
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        assert reader.getnchannels() == 2
        assert reader.getframerate() == 22050
        assert reader.getnframes() == 24 * 22050


def test_melody_events_reject_invalid_energy() -> None:
    try:
        list(melody_events(0, 4, "extreme", 120))
    except ValueError as exc:
        assert "energy" in str(exc)
    else:
        raise AssertionError("invalid energy must be rejected")
