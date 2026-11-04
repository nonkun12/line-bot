import pytest

from agents.music.midi_composer import build_midi_bytes, write_midi_file
from agents.music.score_plan import build_music_plan
from agents.video.scenario import build_scenario


def _plan():
    scenario = build_scenario(
        "A small journey from uncertainty to hope",
        duration_seconds=30,
        scene_count=3,
    )
    return build_music_plan(scenario)


def test_builds_deterministic_valid_type_one_midi_with_four_tracks():
    plan = _plan()
    first = build_midi_bytes(plan)
    second = build_midi_bytes(plan)
    assert first == second
    assert first[:4] == b"MThd"
    assert int.from_bytes(first[4:8], "big") == 6
    assert int.from_bytes(first[8:10], "big") == 1
    assert int.from_bytes(first[10:12], "big") == 4
    assert int.from_bytes(first[12:14], "big") == 480
    assert first.count(b"MTrk") == 4


def test_writes_new_midi_artifact_without_overwriting(tmp_path):
    path = tmp_path / "music" / "original.mid"
    result = write_midi_file(_plan(), path, bpm=96)
    assert path.exists()
    assert path.read_bytes().startswith(b"MThd")
    assert result["status"] == "generated"
    assert result["tracks"] == 4
    with pytest.raises(FileExistsError):
        write_midi_file(_plan(), path, bpm=96)


def test_rejects_invalid_cue_timing_and_bpm():
    plan = _plan()
    plan["cues"][0]["end_seconds"] = plan["duration_seconds"] + 1
    with pytest.raises(ValueError, match="invalid timing"):
        build_midi_bytes(plan)
    with pytest.raises(ValueError, match="bpm"):
        build_midi_bytes(_plan(), bpm=300)
