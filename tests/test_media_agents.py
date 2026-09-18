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
    assert "再生連携はまだ接続していません" in response.text


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
