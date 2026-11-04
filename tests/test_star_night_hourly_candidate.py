from datetime import datetime, timezone
import json
import wave

import pytest

from scripts.star_night_hourly_candidate import build_candidate


def test_candidate_contains_editable_story_and_game_assets(tmp_path):
    out = tmp_path / "candidate"
    result = build_candidate(out, now=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc))
    assert result["status"] == "candidate_created"
    scenario = json.loads((out / "scenario.json").read_text())
    assert len(scenario["scenes"]) == 5
    assert sum(scene["duration"] for scene in scenario["scenes"]) == 15
    assert (out / "screenplay.md").is_file()
    assert (out / "storyboard.json").is_file()
    assert (out / "shot_list.json").is_file()
    assert (out / "game_story_graph.json").is_file()


def test_candidate_generates_original_midi_and_valid_wav(tmp_path):
    out = tmp_path / "candidate"
    build_candidate(out)
    midi = (out / "original_music.mid").read_bytes()
    assert midi.startswith(b"MThd")
    with wave.open(str(out / "original_music.wav"), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 22050
        assert wav.getnframes() == 15 * 22050


def test_hourly_focus_rotates_and_requires_review(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    a = build_candidate(first, now=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc))
    b = build_candidate(second, now=datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc))
    assert a["task_focus"] != b["task_focus"]
    task = json.loads((second / "hourly_task.json").read_text())
    assert task["requires_critic_and_human_approval"] is True


def test_existing_output_is_never_overwritten(tmp_path):
    out = tmp_path / "candidate"
    build_candidate(out)
    with pytest.raises(FileExistsError):
        build_candidate(out)
