from copy import deepcopy

import pytest

from agents.video_music_pipeline import VideoMusicPipeline, run_video_music_pipeline
from agents.music.node import MusicAgent
from agents.video.node import VideoAgent
from core.agents import AgentRequest, AgentResponse


def test_video_music_pipeline_hands_off_same_scenario_and_matches_every_cue():
    request = AgentRequest(
        "user-1",
        "海辺の町を題材にした映像シナリオを作って",
        channel="test",
        metadata={
            "duration_seconds": 181,
            "scene_count": 5,
            "genre": "ドキュメンタリー",
            "music_genre": "シネマティック・アンビエント",
            "instrumentation": "ピアノ、弦楽器、環境音",
        },
    )
    response = run_video_music_pipeline(request)

    assert response.metadata["mode"] == "video_music_pipeline"
    assert response.metadata["handoff"]["scenario_validated"] is True
    assert response.metadata["handoff"]["from"] == "video"
    assert response.metadata["handoff"]["to"] == "music"
    scenario = response.metadata["scenario"]
    plan = response.metadata["music_plan"]
    assert plan["source_scenario_title"] == scenario["title"]
    assert plan["duration_seconds"] == 181
    assert len(plan["cues"]) == len(scenario["scenes"]) == 5
    for scene, cue in zip(scenario["scenes"], plan["cues"]):
        assert cue["scene_id"] == scene["scene_id"]
        assert cue["start_seconds"] == scene["time_start_seconds"]
        assert cue["end_seconds"] == scene["time_start_seconds"] + scene["duration_seconds"]
        assert cue["emotional_intent"] == scene["music_sync"]["emotional_intent"]
        assert cue["energy"] == scene["music_sync"]["energy"]
    assert response.metadata["rendering_status"] == "not_generated"


def test_pipeline_rejects_non_video_request():
    request = AgentRequest("user-1", "明日の天気を教えて")
    with pytest.raises(ValueError, match="not a video-production request"):
        VideoMusicPipeline().run(request)


def test_pipeline_requires_explicit_scenario_request():
    request = AgentRequest("user-1", "動画を編集して")
    with pytest.raises(ValueError, match="explicitly ask for a scenario"):
        VideoMusicPipeline().run(request)


def test_pipeline_rejects_music_plan_that_does_not_match_scenario():
    class WrongMusicAgent(MusicAgent):
        def handle(self, request):
            response = super().handle(request)
            plan = dict(response.metadata["music_plan"])
            plan["duration_seconds"] += 1
            metadata = dict(response.metadata)
            metadata["music_plan"] = plan
            return AgentResponse(response.text, metadata)

    request = AgentRequest(
        "user-1", "短編映像のシナリオを作って",
        metadata={"duration_seconds": 60, "scene_count": 3},
    )
    with pytest.raises(ValueError, match="duration differs"):
        VideoMusicPipeline(music_agent=WrongMusicAgent()).run(request)


def test_pipeline_does_not_mutate_original_request_metadata():
    original = {
        "duration_seconds": 60,
        "scene_count": 3,
        "music_genre": "ambient",
    }
    before = deepcopy(original)
    request = AgentRequest(
        "user-1", "森を舞台にした映像シナリオを作って",
        metadata=original,
    )
    VideoMusicPipeline().run(request)
    assert original == before


def test_pipeline_exposes_dependency_ordered_goal_jobs_after_handoff():
    response = run_video_music_pipeline(AgentRequest(
        "user-1", "夜明けの映像シナリオを作って",
        metadata={"duration_seconds": 60, "scene_count": 3},
    ))
    jobs = {job["id"]: job for job in response.metadata["goal_jobs"]}
    assert "music_composition" in jobs
    assert "audiovisual_sync_review" in jobs
    assert set(jobs["audiovisual_sync_review"]["depends_on"]) == {
        "shot_list", "music_composition"
    }
