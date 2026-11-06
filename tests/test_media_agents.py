from core.agents import AgentRequest
from agents.music.node import MusicAgent
from agents.video.node import VideoAgent


def test_music_agent_handles_music_requests() -> None:
    agent = MusicAgent()
    request = AgentRequest("u1", "作曲を手伝って")
    assert agent.can_handle(request)
    response = agent.handle(request)
    assert response.metadata["feature"] == "music"
    assert response.metadata["status"] == "online"
    assert response.metadata["mode"] == "composition"
    assert "音楽AI" in response.text


def test_music_agent_playlist_mode_is_explicit_about_unconnected_playback() -> None:
    response = MusicAgent().handle(AgentRequest("u1", "プレイリストを作って"))
    assert response.metadata["mode"] == "playlist"
    assert "音源再生・配信連携はまだ接続していません" in response.text


def test_video_agent_handles_video_requests() -> None:
    agent = VideoAgent()
    request = AgentRequest("u1", "動画の台本を作って")
    assert agent.can_handle(request)
    response = agent.handle(request)
    assert response.metadata["feature"] == "video"
    assert response.metadata["status"] == "online"
    assert response.metadata["mode"] == "script"
    assert "映像AI" in response.text


def test_video_agent_editing_mode_is_explicit_about_rendering_limit() -> None:
    response = VideoAgent().handle(AgentRequest("u1", "動画を編集したい"))
    assert response.metadata["mode"] == "editing"
    assert "実編集・書き出し・配信連携はまだ接続していません" in response.text


def test_music_agent_accepts_video_scenario_and_returns_synchronized_score_plan() -> None:
    from agents.video.scenario import build_scenario

    scenario = build_scenario("夕暮れの海辺", duration_seconds=90, scene_count=3)
    request = AgentRequest(
        "u1",
        "映像に合わせて音楽を設計",
        metadata={"scenario": scenario, "music_genre": "cinematic"},
    )
    response = MusicAgent().handle(request)
    assert response.metadata["mode"] == "audiovisual_score_plan"
    plan = response.metadata["music_plan"]
    assert plan["source_scenario_title"] == scenario["title"]
    assert len(plan["cues"]) == len(scenario["scenes"])
    assert plan["rendering_status"] == "not_generated"


def test_music_agent_uses_real_line_breaks_for_scenario_reply():
    from agents.video.scenario import build_scenario

    scenario = build_scenario("映像と音楽", duration_seconds=60, scene_count=3)
    response = MusicAgent().handle(AgentRequest(
        "u1", "映像に合わせて作曲", metadata={"scenario": scenario}
    ))
    assert "\\n" not in response.text
    assert "\n" in response.text


def test_music_agent_returns_validation_message_for_invalid_scenario():
    response = MusicAgent().handle(AgentRequest(
        "u1", "映像に合わせて作曲",
        metadata={"scenario": {"schema_version": "invalid"}},
    ))
    assert response.metadata["status"] == "invalid_request"
    assert "確認してください" in response.text


def test_video_agent_accepts_english_scenario_keyword():
    response = VideoAgent().handle(AgentRequest("u1", "Create a scenario for a short film"))
    assert response.metadata["mode"] == "scenario"
    assert response.metadata["scenario"]["schema_version"] == "video-scenario.v1"


def test_video_agent_handles_invalid_metadata_without_raising():
    response = VideoAgent().handle(AgentRequest(
        "u1", "シナリオを作って",
        metadata={"duration_seconds": "180", "scene_count": 30},
    ))
    assert response.metadata["status"] == "invalid_request"
    assert "確認してください" in response.text
