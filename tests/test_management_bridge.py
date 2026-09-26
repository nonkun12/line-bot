from __future__ import annotations

from agents.stocks.node import StocksAgent
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


class OutOfScopeDependencyPlanner(ManagementPlanner):
    def plan(self, request, decision, feedback=()):
        return ManagementPlan(
            objective="model emitted an out-of-scope dependency",
            decision=decision,
            tasks=(
                AgentTask(
                    "general-task",
                    AgentRole.GENERAL,
                    "General planning context.",
                    resources=frozenset({"general"}),
                ),
                AgentTask(
                    "english-task",
                    AgentRole.ENGLISH,
                    "Teach English.",
                    resources=frozenset({"english"}),
                    depends_on=("general-task",),
                ),
                AgentTask(
                    "music-task",
                    AgentRole.MUSIC,
                    "Plan music.",
                    resources=frozenset({"music"}),
                ),
            ),
        )


def test_management_bridge_replaces_out_of_scope_dependencies_without_widening_roles(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    seen: list[AgentTask] = []

    class RecordingExecutor(FakeExecutor):
        def execute(self, task: AgentTask) -> AgentResult:
            seen.append(task)
            return super().execute(task)

    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.ENGLISH: RecordingExecutor(AgentRole.ENGLISH),
            AgentRole.MUSIC: RecordingExecutor(AgentRole.MUSIC),
        },
    )

    reply = run_management_request(
        "u1",
        "音楽作曲と英語の学習",
        planner=OutOfScopeDependencyPlanner(),
    )

    assert "【English】" in reply
    assert "【Music】" in reply
    assert {task.role for task in seen} == {AgentRole.ENGLISH, AgentRole.MUSIC}
    assert all("general-task" not in task.depends_on for task in seen)


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


def test_management_bridge_binds_stock_task_to_user_ticker(monkeypatch) -> None:
    from core.management_bridge import _bind_source_instructions

    monkeypatch.setattr(
        StocksAgent,
        "_resolve_ticker",
        classmethod(lambda cls, _message: ("7203.T", "トヨタ")),
    )
    plan = StaticPlanner().plan(
        ManagementRequest("u1", "AIニュースとトヨタ株価"),
        ManagementDecision(Specialist.NEWS, "multi", 0.95),
    )
    bound = _bind_source_instructions(plan, "AIニュースとトヨタ株価")
    instructions = {task.role: task.instruction for task in bound.tasks}
    assert instructions[AgentRole.NEWS] == "AI NEWS"
    assert instructions[AgentRole.STOCKS] == "ticker 7203.T"


def test_management_bridge_detects_news_and_toyota_stock_as_two_specialists() -> None:
    roles = specialist_roles_for_message("AI NEWSとトヨタの株価を教えて")
    assert roles == frozenset({AgentRole.NEWS, AgentRole.STOCKS})
    assert should_route_to_management_ai("AI NEWSとトヨタの株価を教えて")


class ClosedLoopPlanner(ManagementPlanner):
    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    def plan(self, request, decision, feedback=()):
        self.feedback.append(tuple(feedback))
        if len(self.feedback) == 1:
            return ManagementPlan(
                objective="bounded handoff",
                decision=decision,
                tasks=(
                    AgentTask(
                        "news-first",
                        AgentRole.NEWS,
                        "Collect initial AI news evidence.",
                        resources=frozenset({"news"}),
                    ),
                    AgentTask(
                        "stocks-first",
                        AgentRole.STOCKS,
                        "Collect initial stock evidence.",
                        resources=frozenset({"stocks"}),
                    ),
                ),
                continue_after_round=True,
            )
        return ManagementPlan(
            objective="bounded follow-up",
            decision=decision,
            tasks=(
                AgentTask(
                    "news-followup",
                    AgentRole.NEWS,
                    "Summarize the next bounded step from the observations.",
                    resources=frozenset({"news"}),
                ),
            ),
            continue_after_round=False,
        )


class RecordingLoopExecutor(FakeExecutor):
    def __init__(self, role: AgentRole) -> None:
        super().__init__(role)
        self.calls: list[str] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls.append(task.task_id)
        return AgentResult(task.task_id, True, f"{self.role.value} result for {task.task_id}")


def test_run_management_request_feeds_results_into_one_bounded_next_round(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    news = RecordingLoopExecutor(AgentRole.NEWS)
    stocks = RecordingLoopExecutor(AgentRole.STOCKS)
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: news,
            AgentRole.STOCKS: stocks,
        },
    )

    planner = ClosedLoopPlanner()
    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=planner,
    )

    assert planner.feedback[0] == ()
    assert planner.feedback[1]
    assert "news-first" in planner.feedback[1][0]
    assert news.calls == ["news-first", "news-followup"]
    assert stocks.calls == ["stocks-first"]
    assert "news-first" in reply
    assert "news-followup" in reply
    assert "stocks-first" in reply


def test_run_management_request_does_not_fallback_after_followup_planning_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    news = RecordingLoopExecutor(AgentRole.NEWS)
    stocks = RecordingLoopExecutor(AgentRole.STOCKS)
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: news,
            AgentRole.STOCKS: stocks,
        },
    )

    class FailOnFollowupPlanner(ManagementPlanner):
        def __init__(self) -> None:
            self.calls = 0

        def plan(self, request, decision, feedback=()):
            self.calls += 1
            if self.calls == 2:
                raise ManagementPlanningError("follow-up plan rejected")
            return ManagementPlan(
                objective="bounded first round",
                decision=decision,
                tasks=(
                    AgentTask(
                        "news-first",
                        AgentRole.NEWS,
                        "Collect initial AI news evidence.",
                        resources=frozenset({"news"}),
                    ),
                    AgentTask(
                        "stocks-first",
                        AgentRole.STOCKS,
                        "Collect initial stock evidence.",
                        resources=frozenset({"stocks"}),
                    ),
                ),
                continue_after_round=True,
            )

    planner = FailOnFollowupPlanner()
    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=planner,
    )

    assert reply is not None
    assert "同じ専門AIを再実行せず" in reply
    assert planner.calls == 2
    assert news.calls == ["news-first"]
    assert stocks.calls == ["stocks-first"]


def test_run_management_request_closed_loop_never_exceeds_two_rounds(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    news = RecordingLoopExecutor(AgentRole.NEWS)
    stocks = RecordingLoopExecutor(AgentRole.STOCKS)
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: news,
            AgentRole.STOCKS: stocks,
        },
    )

    class AlwaysContinuePlanner(ManagementPlanner):
        def __init__(self) -> None:
            self.calls = 0

        def plan(self, request, decision, feedback=()):
            self.calls += 1
            return ManagementPlan(
                objective="bounded",
                decision=decision,
                tasks=(
                    AgentTask(
                        f"round-{self.calls}",
                        AgentRole.NEWS,
                        "Collect bounded evidence.",
                        resources=frozenset({"news"}),
                    ),
                ),
                continue_after_round=True,
            )

    planner = AlwaysContinuePlanner()
    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=planner,
    )

    assert planner.calls == 2
    assert news.calls == ["round-1", "round-2"]
    assert stocks.calls == ["stocks-task"]
    assert "round-2" in reply
