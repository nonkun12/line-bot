from core.distributed_agent_bridge import build_agent_registry
from core.multi_agent import AgentRole


class FakeAgent:
    name = "ai_news"
    enabled = True

    def can_handle(self, request):
        return request.message == "AI NEWSをテスト"

    def handle(self, request):
        class Response:
            text = "news-ready"
        return Response()


def test_bridge_registers_explicit_news_executor():
    class Registry:
        def get(self, name):
            if name == "ai_news":
                return FakeAgent()
            return None

    executors = build_agent_registry(Registry()).build()
    assert AgentRole.NEWS in executors
    result = executors[AgentRole.NEWS].execute(
        __import__("core.multi_agent", fromlist=["AgentTask"]).AgentTask(
            task_id="req-1",
            role=AgentRole.NEWS,
            instruction="AI NEWSをテスト",
        )
    )
    assert result.success is True
    assert result.summary == "news-ready"

def test_distributed_video_executor_runs_scenario_music_pipeline(monkeypatch):
    from agents.video.node import VideoAgent
    from core.multi_agent import AgentTask

    class Registry:
        def get(self, name):
            if name == "video":
                return VideoAgent()
            raise KeyError(name)

    monkeypatch.setattr(
        "core.distributed_agent_bridge.assert_specialist_approved",
        lambda role: None,
    )
    executors = build_agent_registry(Registry()).build()
    result = executors[AgentRole.VIDEO].execute(
        AgentTask(
            task_id="video-scenario-1",
            role=AgentRole.VIDEO,
            instruction="海辺の短編映像と音楽のシナリオを作って",
        )
    )
    assert result.success is True
    assert "Video AI → Music AI 連携完了" in result.summary
    assert "MIDI作曲データ：生成済み" in result.summary


def test_distributed_video_executor_keeps_non_scenario_behavior(monkeypatch):
    from agents.video.node import VideoAgent
    from core.multi_agent import AgentTask

    class Registry:
        def get(self, name):
            if name == "video":
                return VideoAgent()
            raise KeyError(name)

    monkeypatch.setattr(
        "core.distributed_agent_bridge.assert_specialist_approved",
        lambda role: None,
    )
    executors = build_agent_registry(Registry()).build()
    result = executors[AgentRole.VIDEO].execute(
        AgentTask(
            task_id="video-edit-1",
            role=AgentRole.VIDEO,
            instruction="動画を編集して",
        )
    )
    assert result.success is True
    assert "動画の実編集" in result.summary
    assert "Video AI → Music AI 連携完了" not in result.summary
