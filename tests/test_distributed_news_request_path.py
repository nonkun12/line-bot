from __future__ import annotations

import pytest

from core.agents import AgentResponse
from core.multi_agent import AgentRole
from core import request_path


class FakeMusicAgent:
    name = "music"
    description = "fake"
    priority = 1
    enabled = True

    def can_handle(self, request):
        return True

    def handle(self, request):
        return AgentResponse(text="分散AI経由の音楽結果", metadata={"source": "fake-music"})


class FakeAgent:
    name = "ai_news"
    description = "fake"
    priority = 1
    enabled = True

    def can_handle(self, request):
        return True

    def handle(self, request):
        return AgentResponse(
            text="分散AI経由のAI NEWS結果",
            metadata={"source": "fake-news"},
        )


class FakeRegistry:
    def get(self, name):
        if name == "ai_news":
            return FakeAgent()
        return None


def test_distributed_news_request_uses_news_executor(monkeypatch):
    monkeypatch.setattr(
        request_path,
        "build_core_agent_registry",
        lambda: FakeRegistry(),
    )

    result = request_path.run_core_request(
        "user-1",
        "AI NEWSをテスト",
        channel="line",
        metadata={"test": True},
    )

    assert result["intent"] == "distributed_news"
    assert result["route"] == "distributed:news"
    assert result["specialists"] == ["news"]
    assert result["agent_results"]["news"]["status"] == "ok"
    assert result["agent_results"]["news"]["metadata"] == {
        "role": AgentRole.NEWS.value,
        "distributed": True,
    }
    assert result["final_reply"] == "分散AI経由のAI NEWS結果"


def test_distributed_news_request_fails_closed_when_news_executor_missing(monkeypatch):
    monkeypatch.setattr(
        request_path,
        "build_core_agent_registry",
        lambda: FakeRegistryWithoutNews(),
    )

    with pytest.raises(RuntimeError, match="missing executor for role: news"):
        request_path.run_core_request("user-1", "AI NEWSをテスト", channel="line")


class FakeRegistryWithoutNews:
    def get(self, name):
        return None


class FakeRegistryWithMusic(FakeRegistry):
    def get(self, name):
        if name == "music":
            return FakeMusicAgent()
        return super().get(name)


def test_distributed_music_request_uses_music_executor(monkeypatch):
    monkeypatch.setattr(request_path, "build_core_agent_registry", lambda: FakeRegistryWithMusic())
    result = request_path.run_core_request("user-1", "音楽をテスト", channel="line")
    assert result["intent"] == "distributed_music"
    assert result["route"] == "distributed:music"
    assert result["specialists"] == ["music"]
    assert result["agent_results"]["music"]["status"] == "ok"
    assert result["final_reply"] == "分散AI経由の音楽結果"


class FakeVideoAgent:
    name = "video"
    description = "fake"
    priority = 1
    enabled = True
    def can_handle(self, request): return True
    def handle(self, request): return AgentResponse(text="分散AI経由の動画結果", metadata={"source": "fake-video"})


def test_distributed_video_request_uses_video_executor(monkeypatch):
    original = FakeRegistry.get
    def get(self, name):
        if name == "video":
            return FakeVideoAgent()
        return original(self, name)
    monkeypatch.setattr(FakeRegistry, "get", get)
    monkeypatch.setattr(request_path, "build_core_agent_registry", lambda: FakeRegistry())
    result = request_path.run_core_request("user-1", "動画をテスト", channel="line")
    assert result["intent"] == "distributed_video"
    assert result["route"] == "distributed:video"
    assert result["specialists"] == ["video"]
    assert result["agent_results"]["video"]["status"] == "ok"
    assert result["final_reply"] == "分散AI経由の動画結果"
