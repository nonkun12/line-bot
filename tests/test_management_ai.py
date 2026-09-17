from __future__ import annotations

import pytest

from core.agent_communication import AgentMessage, AgentMessageBus
from core.management_ai import ManagementAI, ManagementPlan, ManagementPlanner, ManagementPlanningError, ModelManagementPlanner
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
    def plan(self, request: ManagementRequest, decision: ManagementDecision) -> ManagementPlan:
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
