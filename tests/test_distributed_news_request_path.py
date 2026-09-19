from __future__ import annotations

import pytest

from core.agents import AgentResponse
from core.multi_agent import AgentRole
from core.management_contract import Specialist, specialist_boundary
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


class FakeJobsAgent:
    name = "job_seeking"
    description = "fake"
    priority = 1
    enabled = True
    def can_handle(self, request): return True
    def handle(self, request): return AgentResponse(text="分散AI経由の求人結果", metadata={"source": "fake-jobs"})


def test_distributed_jobs_request_uses_jobs_executor(monkeypatch):
    original = FakeRegistry.get
    def get(self, name):
        if name == "job_seeking":
            return FakeJobsAgent()
        return original(self, name)
    monkeypatch.setattr(FakeRegistry, "get", get)
    monkeypatch.setattr(request_path, "build_core_agent_registry", lambda: FakeRegistry())
    result = request_path.run_core_request("user-1", "求人をテスト", channel="line")
    assert result["intent"] == "distributed_jobs"
    assert result["route"] == "distributed:jobs"
    assert result["specialists"] == ["jobs"]
    assert result["agent_results"]["jobs"]["status"] == "ok"
    assert result["final_reply"] == "分散AI経由の求人結果"


class FakeMarketAgent:
    name = "global_market"
    description = "fake"
    priority = 1
    enabled = True
    def can_handle(self, request): return True
    def handle(self, request): return AgentResponse(text="分散AI経由の市場結果", metadata={"source": "fake-market"})


def test_distributed_market_request_uses_market_executor(monkeypatch):
    original = FakeRegistry.get
    def get(self, name):
        if name == "global_market":
            return FakeMarketAgent()
        return original(self, name)
    monkeypatch.setattr(FakeRegistry, "get", get)
    monkeypatch.setattr(request_path, "build_core_agent_registry", lambda: FakeRegistry())
    result = request_path.run_core_request("user-1", "世界市場をテスト", channel="line")
    assert result["intent"] == "distributed_market"
    assert result["route"] == "distributed:market"
    assert result["specialists"] == ["market"]
    assert result["agent_results"]["market"]["status"] == "ok"
    assert result["final_reply"] == "分散AI経由の市場結果"


class FakeDomainAgent:
    def __init__(self, name, text):
        self.name = name
        self.description = "fake"
        self.priority = 1
        self.enabled = True
        self._text = text

    def can_handle(self, request):
        return True

    def handle(self, request):
        return AgentResponse(text=self._text, metadata={"source": self.name})


class FakeFourDomainRegistry:
    def __init__(self):
        self._agents = {
            "music": FakeDomainAgent("music", "音楽OK"),
            "video": FakeDomainAgent("video", "動画OK"),
            "job_seeking": FakeDomainAgent("job_seeking", "求人OK"),
            "global_market": FakeDomainAgent("global_market", "市場OK"),
        }

    def get(self, name):
        return self._agents.get(name)


def test_four_explicit_domains_dispatch_in_parallel(monkeypatch):
    monkeypatch.setattr(
        request_path,
        "build_core_agent_registry",
        lambda: FakeFourDomainRegistry(),
    )

    result = request_path.run_core_request(
        "user-1",
        "分散AIテスト：音楽をテストして 動画をテストして 求人を調べて 市場を調べて",
        channel="line",
    )

    assert result["intent"] == "multi_specialist"
    assert result["specialists"] == ["music", "video", "jobs", "market"]
    assert result["parallel"] is True
    assert result["max_workers"] == 4
    assert result["failed_specialists"] == []
    assert result["agent_results"]["music"]["status"] == "ok"
    assert result["agent_results"]["video"]["status"] == "ok"
    assert result["agent_results"]["jobs"]["status"] == "ok"
    assert result["agent_results"]["market"]["status"] == "ok"
    assert result["final_reply"] == "音楽OK\n\n動画OK\n\n求人OK\n\n市場OK"


def test_management_capability_gate_covers_all_dispatched_specialists():
    expected = {
        "news": "news_retrieval",
        "stocks": "stock_quotes",
        "english": "english_learning",
        "voice": "text_to_speech",
        "music": "music_planning",
        "video": "video_planning",
        "jobs": "job_search",
        "market": "market_summary",
    }
    for specialist, capability in expected.items():
        boundary = specialist_boundary(Specialist(specialist))
        assert capability in boundary.capabilities
