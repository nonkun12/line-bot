from copy import deepcopy

import pytest

from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario
from agents.video.sync_edit_plan import build_sync_aware_edit_plan


def _edl():
    scenario = build_scenario("夜明けに向かう小さな旅", duration_seconds=40, scene_count=4)
    return build_edit_decision_list(scenario, build_music_plan(scenario), bpm=120)


def test_sync_edit_plan_maps_authored_events_to_output_frames_without_moving_them():
    edl = _edl()
    plan = build_sync_aware_edit_plan(edl, fps=24)

    assert plan["schema_version"] == "audiovisual-sync-edit-plan.v1"
    assert plan["event_count"] == len(edl["sync_events"]) == 12
    for suggestion in plan["suggestions"]:
        assert suggestion["frame_index"] == round(
            suggestion["authored_at_seconds"] * 24
        )
        assert suggestion["frame_time_seconds"] == pytest.approx(
            suggestion["frame_index"] / 24
        )
        assert suggestion["timing_preserved"] is True
        assert suggestion["automatic_cut"] is False


def test_sync_edit_plan_preserves_expressive_offsets_without_forced_cuts():
    edl = _edl()
    # The generated default score intentionally places its current anchors on
    # beats. Inject a deliberate authored pause to exercise the off-beat path.
    expressive = edl["beat_sync"]["events"][0]
    expressive["authored_at_seconds"] += 0.17
    expressive["alignment"] = "expressive_offset"
    visual_point = next(
        point
        for scene in edl["video_track"]
        if scene["scene_id"] == expressive["scene_id"]
        for point in scene["visual_sync_points"]
        if point["event"] == expressive["event"]
    )
    visual_point["at_seconds"] = expressive["authored_at_seconds"]
    plan = build_sync_aware_edit_plan(edl, fps=30)
    suggestion = next(
        item for item in plan["suggestions"]
        if item["scene_id"] == expressive["scene_id"]
        and item["event"] == expressive["event"]
        and item["authored_at_seconds"] == expressive["authored_at_seconds"]
    )

    assert suggestion["recommended_action"] == "preserve_expressive_timing"
    assert suggestion["automatic_cut"] is False


def test_sync_edit_plan_marks_on_beat_events_as_editorial_candidates_only():
    edl = _edl()
    on_beat = next(
        event for event in edl["beat_sync"]["events"]
        if event["alignment"] == "on_beat"
    )
    plan = build_sync_aware_edit_plan(edl)
    suggestion = next(
        item for item in plan["suggestions"]
        if item["scene_id"] == on_beat["scene_id"]
        and item["event"] == on_beat["event"]
        and item["authored_at_seconds"] == on_beat["authored_at_seconds"]
    )

    assert suggestion["recommended_action"] == "consider_cut_or_visual_emphasis"
    assert suggestion["automatic_cut"] is False


@pytest.mark.parametrize("fps", [0, 61, True, 24.0])
def test_sync_edit_plan_rejects_invalid_fps(fps):
    with pytest.raises(ValueError, match="fps"):
        build_sync_aware_edit_plan(_edl(), fps=fps)


def test_sync_edit_plan_rejects_out_of_scene_sync_anchor():
    edl = deepcopy(_edl())
    edl["video_track"][0]["visual_sync_points"][0]["at_seconds"] = 999

    with pytest.raises(ValueError, match="visual sync point"):
        build_sync_aware_edit_plan(edl)
