from __future__ import annotations

import pytest

from core.agent_communication import AgentMessage, AgentMessageBus
from core.management_ai import (
    ManagementAI,
    ManagementCycleRun,
    ManagementPlan,
    ManagementPlanner,
    ManagementPlanningError,
    ModelManagementPlanner,
)
from core.management_contract import ManagementDecision, ManagementRequest, Specialist
from core.multi_agent import AgentResult, AgentRole, AgentTask


def test_message_bus_requires_safety_and_round_trips() -> None:
    bus = AgentMessageBus(max_messages=2)
    message = AgentMessage(
        message_id="stocks-1:result",
        sender="stocks-1",
        recipient="management",
        message_type="task_result",
        content="analysis complete",
        safety_constraints=("result-only",),
    )
    bus.send(message)
    assert bus.peek("management") == (message,)
    assert bus.receive("management") == (message,)
    assert bus.receive("management") == ()


def test_message_bus_rejects_unconstrained_message() -> None:
    bus = AgentMessageBus()
    with pytest.raises(ValueError, match="safety constraint"):
        bus.send(
            AgentMessage(
                message_id="m1",
                sender="a",
                recipient="b",
                message_type="task",
                content="hello",
            )
        )


def test_management_planner_validates_bounded_parallel_plan() -> None:
    payload = (
        '{"objective":"compare market data",'
        '"parallel_safe":true,'
        '"tasks":['
        '{"task_id":"stocks-a","role":"stocks","instruction":"Analyze AAPL.",'
        '"resources":["aapl"],"depends_on":[],"priority":2},'
        '{"task_id":"stocks-b","role":"stocks","instruction":"Analyze MSFT.",'
        '"resources":["msft"],"depends_on":[],"priority":1}'
        ']}'
    )
    planner = ModelManagementPlanner(model_call=lambda prompt: payload)
    request = ManagementRequest("u1", "AAPLとMSFTを比較して")
    plan = planner.plan(
        request,
        ManagementDecision(Specialist.STOCKS, "matched stocks", 0.95),
    )
    assert plan.parallel_safe
    assert len(plan.tasks) == 2


def test_management_planner_rejects_unsafe_instruction() -> None:
    planner = ModelManagementPlanner(
        model_call=lambda prompt: (
            '{"objective":"x","tasks":['
            '{"task_id":"x","role":"stocks","instruction":"git commit the result",'
            '"resources":["repo"],"depends_on":[],"priority":1}'
            ']}'
        )
    )
    with pytest.raises(ManagementPlanningError, match="unsafe instruction"):
        planner.plan(
            ManagementRequest("u1", "株価を見て"),
            ManagementDecision(Specialist.STOCKS, "matched stocks", 0.95),
        )


class Executor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role
        self.calls: list[str] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls.append(task.task_id)
        return AgentResult(task.task_id, True, f"{self.role.value}:done")


class StaticPlanner(ManagementPlanner):
    def plan(
        self,
        request: ManagementRequest,
        decision: ManagementDecision,
        feedback=(),
    ) -> ManagementPlan:
        tasks = (
            AgentTask(
                "voice",
                AgentRole.VOICE,
                "Prepare a voice response.",
                resources=frozenset({"voice"}),
            ),
            AgentTask(
                "news",
                AgentRole.NEWS,
                "Collect news summaries.",
                resources=frozenset({"news"}),
            ),
        )
        return ManagementPlan(
            objective="two independent specialist tasks",
            decision=decision,
            tasks=tasks,
            parallel_safe=True,
        )


def test_management_ai_dispatches_independent_specialists_and_collects_results() -> None:
    voice = Executor(AgentRole.VOICE)
    news = Executor(AgentRole.NEWS)
    manager = ManagementAI(
        {AgentRole.VOICE: voice, AgentRole.NEWS: news},
        planner=StaticPlanner(),
        max_workers=2,
        isolated=True,
    )

    result = manager.run(ManagementRequest("u1", "音声とニュースを準備して"))

    assert result.success
    assert result.plan.parallel_safe
    assert result.distributed.success
    assert set(voice.calls) == {"voice"}
    assert set(news.calls) == {"news"}

    messages = manager.message_bus.receive("management")
    assert {m.message_type for m in messages} == {"task_result"}
    assert {m.sender for m in messages} == {"voice", "news"}


def test_parallel_management_requires_explicit_isolation() -> None:
    with pytest.raises(ValueError, match="isolated=True"):
        ManagementAI({}, planner=StaticPlanner(), max_workers=2)

class LoopPlanner(ManagementPlanner):
    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    def plan(
        self,
        request: ManagementRequest,
        decision: ManagementDecision,
        feedback=(),
    ) -> ManagementPlan:
        self.feedback.append(tuple(feedback))
        if len(self.feedback) == 1:
            tasks = (
                AgentTask(
                    "research",
                    AgentRole.NEWS,
                    "Collect initial evidence.",
                    resources=frozenset({"news"}),
                ),
            )
            return ManagementPlan(
                objective="closed loop",
                decision=decision,
                tasks=tasks,
                continue_after_round=True,
            )
        tasks = (
            AgentTask(
                "followup",
                AgentRole.STOCKS,
                "Summarize the next bounded step using the observations.",
                resources=frozenset({"stocks"}),
            ),
        )
        return ManagementPlan(
            objective="closed loop",
            decision=decision,
            tasks=tasks,
            continue_after_round=False,
        )


def test_management_ai_closed_loop_feeds_results_back_to_manager() -> None:
    news = Executor(AgentRole.NEWS)
    stocks = Executor(AgentRole.STOCKS)
    planner = LoopPlanner()
    manager = ManagementAI(
        {AgentRole.NEWS: news, AgentRole.STOCKS: stocks},
        planner=planner,
    )

    cycle = manager.run_closed_loop(
        ManagementRequest("u1", "ニュースと株価を調べて"),
        max_rounds=2,
    )

    assert isinstance(cycle, ManagementCycleRun)
    assert cycle.success
    assert len(cycle.rounds) == 2
    assert planner.feedback[0] == ()
    assert planner.feedback[1]
    assert "research" in planner.feedback[1][0]
    assert news.calls == ["research"]
    assert stocks.calls == ["followup"]
    assert cycle.stopped_reason == "manager stopped the cycle"


def test_management_ai_closed_loop_is_bounded() -> None:
    class AlwaysContinue(LoopPlanner):
        def plan(self, request, decision, feedback=()):
            self.feedback.append(tuple(feedback))
            return ManagementPlan(
                objective="bounded",
                decision=decision,
                tasks=(
                    AgentTask(
                        "task",
                        AgentRole.NEWS,
                        "Collect bounded evidence.",
                        resources=frozenset({"news"}),
                    ),
                ),
                continue_after_round=True,
            )

    planner = AlwaysContinue()
    manager = ManagementAI({AgentRole.NEWS: Executor(AgentRole.NEWS)}, planner=planner)

    cycle = manager.run_closed_loop(
        ManagementRequest("u1", "調べて"),
        max_rounds=2,
    )

    assert len(cycle.rounds) == 2
    assert cycle.stopped_reason == "bounded round limit reached"
