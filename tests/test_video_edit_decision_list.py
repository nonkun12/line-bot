import copy

import pytest

from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario


def _inputs():
    scenario = build_scenario(
        "A quiet town discovers a new light",
        duration_seconds=45,
        scene_count=3,
    )
    return scenario, build_music_plan(scenario)


def test_builds_contiguous_video_and_music_tracks_with_scene_sync():
    scenario, music = _inputs()
    edl = build_edit_decision_list(scenario, music)
    assert edl["schema_version"] == "audiovisual-edl.v1"
    assert edl["status"] == "draft"
    assert edl["duration_seconds"] == 45
    assert len(edl["video_track"]) == len(edl["audio_track"]) == 3
    assert edl["video_track"][0]["start_seconds"] == 0
    assert edl["video_track"][-1]["end_seconds"] == 45
    assert edl["video_track"][0]["camera_motion"] == "slow_push_in"
    assert edl["video_track"][1]["camera_motion"] == "decisive_reveal"
    assert all(item["dialogue_or_narration"] for item in edl["video_track"])
    assert all(item["render_status"] == "not_rendered" for item in edl["audio_track"])
    assert edl["rights_status"] == "assets_not_attached"


def test_rejects_music_cue_outside_scene():
    scenario, music = _inputs()
    broken = copy.deepcopy(music)
    broken["cues"][0]["end_seconds"] = 45
    with pytest.raises(ValueError, match="falls outside its scene"):
        build_edit_decision_list(scenario, broken)


def test_rejects_missing_or_duplicate_scene_cues():
    scenario, music = _inputs()
    missing = copy.deepcopy(music)
    missing["cues"].pop()
    with pytest.raises(ValueError, match="music cue missing"):
        build_edit_decision_list(scenario, missing)
    duplicate = copy.deepcopy(music)
    duplicate["cues"].append(copy.deepcopy(duplicate["cues"][0]))
    with pytest.raises(ValueError, match="duplicated"):
        build_edit_decision_list(scenario, duplicate)
