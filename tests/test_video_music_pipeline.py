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
    assert response.metadata["rendering_status"] == "midi_generated_audio_not_rendered"
    artifact = response.metadata["midi_artifact"]
    import base64
    midi_bytes = base64.b64decode(artifact["content_base64"])
    assert midi_bytes.startswith(b"MThd")
    assert midi_bytes[14:18] == b"MTrk"
    assert artifact["mime_type"] == "audio/midi"
    assert artifact["size_bytes"] == len(midi_bytes)


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


def test_normal_langgraph_video_node_runs_music_handoff_for_scenario_request():
    from graph.graph import video_agent_node

    state = {
        "user_id": "user-1",
        "raw_message": "海辺の短編映像シナリオを作って",
        "channel": "line",
        "metadata": {"duration_seconds": 90, "scene_count": 3},
        "agent_results": {},
    }
    result = video_agent_node(state)
    assert "Video AI → Music AI 連携完了" in result["final_reply"]
    assert result["agent_results"]["video"] == result["final_reply"]
    assert result["metadata"]["video_music_handoff"]["scenario_validated"] is True


def test_normal_langgraph_video_node_preserves_non_scenario_video_behavior():
    from graph.graph import video_agent_node

    state = {
        "user_id": "user-1",
        "raw_message": "動画を編集して",
        "channel": "line",
        "metadata": {},
        "agent_results": {},
    }
    result = video_agent_node(state)
    assert "動画の実編集" in result["final_reply"]
    assert result["metadata"]["video_music_handoff"] is None


def test_core_registry_prefers_video_for_combined_audiovisual_scenario_request():
    from graph.core_registry import build_core_agent_registry
    from core.agents import AgentRequest

    request = AgentRequest(
        "user-1",
        "映像と音楽のシナリオを作って",
    )
    selected = build_core_agent_registry().resolve(request)
    assert selected is not None
    assert selected.name == "video"

def test_pipeline_rejects_music_cue_that_does_not_match_source_scene():
    class WrongCueMusicAgent(MusicAgent):
        def handle(self, request):
            response = super().handle(request)
            metadata = dict(response.metadata)
            plan = dict(metadata["music_plan"])
            cues = [dict(cue) for cue in plan["cues"]]
            cues[0]["start_seconds"] += 1
            plan["cues"] = cues
            metadata["music_plan"] = plan
            return AgentResponse(response.text, metadata)

    request = AgentRequest(
        "user-1", "短編映像のシナリオを作って",
        metadata={"duration_seconds": 60, "scene_count": 3},
    )
    with pytest.raises(ValueError, match="does not match source scene"):
        VideoMusicPipeline(music_agent=WrongCueMusicAgent()).run(request)


def test_pipeline_reply_uses_actual_line_breaks():
    response = run_video_music_pipeline(AgentRequest(
        "user-1", "短編映像のシナリオを作って",
        metadata={"duration_seconds": 60, "scene_count": 3},
    ))
    assert "\\n" not in response.text
    assert "\n" in response.text

def test_script_request_also_chains_video_scenario_into_music():
    from agents.video_music_pipeline import handle_video_request

    response = handle_video_request(AgentRequest(
        "user-1", "短編映画の台本を作って",
        metadata={"duration_seconds": 60, "scene_count": 3},
    ))
    assert response.metadata["mode"] == "video_music_pipeline"
    assert response.metadata["handoff"]["to"] == "music"
    assert response.metadata["scenario"]["status"] == "draft"

def test_midi_generator_rejects_invalid_or_overlapping_cues():
    from agents.music.midi import build_midi_bytes

    with pytest.raises(ValueError, match="invalid timing"):
        build_midi_bytes({
            "duration_seconds": 10,
            "cues": [
                {"scene_id": "SC01", "start_seconds": 0, "end_seconds": 8, "energy": "low"},
                {"scene_id": "SC02", "start_seconds": 7, "end_seconds": 10, "energy": "medium"},
            ],
        })


def test_midi_generator_emits_standard_midi_type_zero_header():
    from agents.music.midi import build_midi_bytes

    midi = build_midi_bytes({
        "duration_seconds": 12,
        "source_scenario_title": "test",
        "cues": [
            {"scene_id": "SC01", "start_seconds": 0, "end_seconds": 6, "energy": "low"},
            {"scene_id": "SC02", "start_seconds": 6, "end_seconds": 12, "energy": "high"},
        ],
    })
    assert midi[:4] == b"MThd"
    assert midi[8:10] == b"\\x00\\x00"
    assert midi[10:12] == b"\\x00\\x01"
    assert midi[14:18] == b"MTrk"
