from __future__ import annotations

from core.agents import AgentRequest
from core.management_contract import ManagementDecision, ManagementRequest, Specialist
from core.management_ai import ManagementPlan, ManagementPlanner
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.management_bridge import (
    run_management_request,
    should_route_to_management_ai,
    specialist_roles_for_message,
)


def test_management_bridge_keeps_broad_world_market_request_on_market_ai() -> None:
    roles = specialist_roles_for_message("世界の株価と為替を教えて")
    assert roles == frozenset({AgentRole.MARKET})
    assert not should_route_to_management_ai("世界の株価と為替を教えて")


def test_management_bridge_detects_market_and_stocks_specialists() -> None:
    roles = specialist_roles_for_message("NYダウと株価を調べて")
    assert roles == frozenset({AgentRole.MARKET, AgentRole.STOCKS})
    assert should_route_to_management_ai("NYダウと株価を調べて")


def test_management_bridge_detects_multiple_specialists() -> None:
    roles = specialist_roles_for_message("AIニュースと株価を調べて")
    assert roles == frozenset({AgentRole.NEWS, AgentRole.STOCKS})
    assert should_route_to_management_ai("AIニュースと株価を調べて")


def test_management_bridge_detects_jobs_and_news_specialists() -> None:
    roles = specialist_roles_for_message("求人とAIニュースを調べて")
    assert roles == frozenset({AgentRole.JOBS, AgentRole.NEWS})
    assert should_route_to_management_ai("求人とAIニュースを調べて")


def test_management_bridge_detects_music_and_video_specialists() -> None:
    roles = specialist_roles_for_message("音楽のBGMと動画の絵コンテを作って")
    assert roles == frozenset({AgentRole.MUSIC, AgentRole.VIDEO})
    assert should_route_to_management_ai("音楽のBGMと動画の絵コンテを作って")


def test_management_bridge_keeps_single_specialist_on_existing_route() -> None:
    assert specialist_roles_for_message("今日の株価を教えて") == frozenset({AgentRole.STOCKS})
    assert not should_route_to_management_ai("今日の株価を教えて")


class StaticPlanner(ManagementPlanner):
    def plan(self, request: ManagementRequest, decision: ManagementDecision, feedback=()) -> ManagementPlan:
        return ManagementPlan(
            objective="multi specialist",
            decision=decision,
            tasks=(
                AgentTask(
                    "news-task",
                    AgentRole.NEWS,
                    "Collect recent AI news headlines.",
                    resources=frozenset({"news"}),
                ),
                AgentTask(
                    "stocks-task",
                    AgentRole.STOCKS,
                    "Summarize the requested stock data.",
                    resources=frozenset({"stocks"}),
                ),
            ),
            parallel_safe=False,
        )


class FakeExecutor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role

    def execute(self, task: AgentTask) -> AgentResult:
        return AgentResult(task.task_id, True, f"{self.role.value} result")


def test_run_management_request_collects_specialist_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        channel="slack",
        planner=StaticPlanner(),
    )

    assert reply == "【AI NEWS】\nnews result\n\n【Stocks】\nstocks result"


def test_run_management_request_returns_none_for_ineligible_request() -> None:
    assert run_management_request(
        "u1",
        "英語を練習したい",
        planner=StaticPlanner(),
    ) is None



def test_run_management_request_falls_back_when_management_execution_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    class BrokenPlanner(StaticPlanner):
        def plan(self, request, decision, feedback=()):
            raise RuntimeError("temporary planner outage")

    assert run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=BrokenPlanner(),
    ) is None



def test_ai_gateway_uses_management_bridge_for_multi_specialist_request(monkeypatch) -> None:
    import app as app_module
    from core.gateway import AIRequest

    calls = []

    monkeypatch.setattr(
        app_module,
        "run_management_request",
        lambda user_id, message, **kwargs: calls.append((user_id, message, kwargs)) or "管理AI統合結果",
    )
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy core route should not run")),
    )

    response = app_module._handle_ai_gateway_request(
        AIRequest("u1", "AIニュースと株価を調べて", channel="slack")
    )

    assert response == "管理AI統合結果"
    assert calls and calls[0][0:2] == ("u1", "AIニュースと株価を調べて")


def test_ai_gateway_falls_back_to_core_when_management_returns_none(monkeypatch) -> None:
    import app as app_module
    from core.gateway import AIRequest

    monkeypatch.setattr(app_module, "run_management_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda *args, **kwargs: {"final_reply": "従来Core結果"},
    )
    monkeypatch.setattr(
        app_module,
        "extract_core_reply",
        lambda result: result["final_reply"],
    )

    response = app_module._handle_ai_gateway_request(
        AIRequest("u1", "AIニュースと株価を調べて", channel="slack")
    )

    assert response == "従来Core結果"


def test_run_management_request_does_not_retry_failed_execution(monkeypatch) -> None:
    class RaisingExecutor(FakeExecutor):
        def execute(self, task: AgentTask) -> AgentResult:
            raise RuntimeError("external side effect failed")

    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: RaisingExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=StaticPlanner(),
    )

    assert reply == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"


def test_run_management_request_does_not_fail_after_empty_specialist_result(