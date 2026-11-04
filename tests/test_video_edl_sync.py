from copy import deepcopy

import pytest

from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario


def test_edl_exposes_music_sync_points_as_visual_timing_anchors():
    scenario = build_scenario("夜明けに向かう小さな旅", duration_seconds=40, scene_count=4)
    music_plan = build_music_plan(scenario)

    edl = build_edit_decision_list(scenario, music_plan)

    assert edl["schema_version"] == "audiovisual-edl.v1"
    assert len(edl["sync_events"]) == 12
    assert edl["sync_events"] == sorted(edl["sync_events"], key=lambda item: item["at_seconds"])
    for scene, cue in zip(edl["video_track"], edl["audio_track"]):
        assert len(scene["visual_sync_points"]) == 3
        assert scene["visual_sync_points"] == cue["sync_points"]
        for point in scene["visual_sync_points"]:
            assert point["at_seconds"] == pytest.approx(
                scene["start_seconds"] + point["scene_offset_seconds"]
            )
            assert scene["start_seconds"] <= point["at_seconds"] <= scene["end_seconds"]


def test_edl_rejects_invalid_or_unbounded_music_sync_points():
    scenario = build_scenario("A small journey", duration_seconds=40, scene_count=4)
    music_plan = build_music_plan(scenario)
    broken = deepcopy(music_plan)
    broken["cues"][0]["sync_points"][1]["at_seconds"] = 999

    with pytest.raises(ValueError, match="sync point"):
        build_edit_decision_list(scenario, broken)


def test_edl_rejects_empty_music_sync_points():
    scenario = build_scenario("A small journey", duration_seconds=40, scene_count=4)
    music_plan = build_music_plan(scenario)
    music_plan["cues"][0]["sync_points"] = []

    with pytest.raises(ValueError, match="sync points"):
        build_edit_decision_list(scenario, music_plan)
