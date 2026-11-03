from agents.video.scenario import build_scenario
from agents.music.score_plan import build_music_plan


def test_music_plan_follows_video_scene_timing_and_emotional_arc():
    scenario = build_scenario("雨上がりの街を歩く", duration_seconds=121, scene_count=4)
    plan = build_music_plan(scenario, genre="アンビエント", instrumentation="ピアノと弦")
    assert plan["status"] == "draft"
    assert plan["duration_seconds"] == 121
    assert plan["rendering_status"] == "not_generated"
    assert len(plan["cues"]) == 4
    for scene, cue in zip(scenario["scenes"], plan["cues"]):
        assert cue["scene_id"] == scene["scene_id"]
        assert cue["start_seconds"] == scene["time_start_seconds"]
        assert cue["end_seconds"] == scene["time_start_seconds"] + scene["duration_seconds"]
        assert cue["sync_points"][0]["at_seconds"] == scene["time_start_seconds"]


def test_music_plan_rejects_invalid_scenario_and_unbounded_options():
    scenario = build_scenario("朝の光", duration_seconds=60, scene_count=3)
    scenario["scenes"][0]["music_sync"]["cue_out_seconds"] = 1000
    try:
        build_music_plan(scenario)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid scenario must not produce a music plan")


def test_music_plan_preserves_emotional_energy_per_scene():
    scenario = build_scenario("感情の曲線", duration_seconds=120, scene_count=4)
    plan = build_music_plan(scenario)
    assert [cue["energy"] for cue in plan["cues"]] == ["low", "medium", "high", "low"]
