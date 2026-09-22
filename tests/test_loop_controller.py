from __future__ import annotations

import pytest

from core.loop_controller import LoopController, LoopObservation, LoopRun
from core.management_ai import ManagementAI, ManagementPlan, ManagementPlanner
from core.management_contract import ManagementRequest
from core.multi_agent import AgentResult, AgentRole, AgentTask


class Executor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role
        self.calls: list[str] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls.append(task.task_id)
        return AgentResult(task.task_id, True, f"{self.role.value}:done")


class Planner(ManagementPlanner):
    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    def plan(self, request, decision, feedback=()):
        self.feedback.append(tuple(feedback))
        if len(self.feedback) == 1:
            return ManagementPlan(
                objective="loop",
                decision=decision,
                tasks=(
                    AgentTask(
                        "research",
                        AgentRole.NEWS,
                        "Collect evidence.",
                        resources=frozenset({"news"}),
                    ),
                ),
                continue_after_round=True,
            )
        return ManagementPlan(
            objective="loop",
            decision=decision,
            tasks=(
                AgentTask(
                    "followup",
                    AgentRole.STOCKS,
                    "Summarize bounded next step.",
                    resources=frozenset({"stocks"}),
                ),
            ),
            continue_after_round=False,
        )


def test_loop_controller_preserves_lineage_and_feeds_observations() -> None:
    planner = Planner()
    manager = ManagementAI(
        {
            AgentRole.NEWS: Executor(AgentRole.NEWS),
            AgentRole.STOCKS: Executor(AgentRole.STOCKS),
        },
        planner=planner,
    )
    loop = LoopController(manager, max_rounds=2).run(
        ManagementRequest("u1", "ニュースと株価を確認して"),
        loop_id="loop-test-1",
    )

    assert isinstance(loop, LoopRun)
    assert loop.success
    assert loop.loop_id == "loop-test-1"
    assert len(loop.iterations) == 2
    assert all(item.loop_id == "loop-test-1" for item in loop.iterations)
    assert all(
        observation.loop_id == "loop-test-1"
        for item in loop.iterations
        for observation in item.observations
    )
    assert planner.feedback[0] == ()
    assert planner.feedback[1]
    assert "loop-test-1" in planner.feedback[1][0]
    assert "research" in planner.feedback[1][0]


def test_management_messages_use_loop_id_as_correlation_when_present() -> None:
    manager = ManagementAI(
        {AgentRole.NEWS: Executor(AgentRole.NEWS)},
        planner=Planner(),
    )
    manager.run(
        ManagementRequest(
            "u1",
            "ニュースを確認して",
            metadata={"loop_id": "loop-test-2"},
        )
    )
    message = manager.message_bus.receive()[0]
    assert message.correlation_id == "loop-test-2"
    assert message.context["loop_id"] == "loop-test-2"


def test_loop_controller_fails_closed_on_round_limit() -> None:
    class AlwaysContinue(Planner):
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

    manager = ManagementAI(
        {AgentRole.NEWS: Executor(AgentRole.NEWS)},
        planner=AlwaysContinue(),
    )
    loop = LoopController(manager, max_rounds=2).run(
        ManagementRequest("u1", "調べて"),
        loop_id="loop-test-3",
    )

    assert loop.stopped_reason == "bounded round limit reached"
    assert len(loop.iterations) == 2


def test_loop_controller_rejects_conflicting_request_loop_id() -> None:
    manager = ManagementAI(
        {AgentRole.NEWS: Executor(AgentRole.NEWS)},
        planner=Planner(),
    )
    request = ManagementRequest(
        "u1",
        "ニュースを確認して",
        metadata={"loop_id": "different"},
    )
    with pytest.raises(ValueError, match="conflicts"):
        LoopController(manager).run(request, loop_id="loop-test-4")


def test_loop_controller_generates_bounded_loop_id_when_omitted() -> None:
    manager = ManagementAI(
        {AgentRole.NEWS: Executor(AgentRole.NEWS)},
        planner=Planner(),
    )
    loop = LoopController(manager, max_rounds=1).run(
        ManagementRequest("u1", "ニュースを確認して")
    )
    assert loop.loop_id
    assert len(loop.loop_id) <= 64


def test_loop_observation_is_bounded_and_immutable() -> None:
    observation = LoopObservation(
        "loop-1",
        1,
        "task-1",
        True,
        "news",
        "done",
    )
    assert observation.summary == "done"
    with pytest.raises(ValueError, match="summary exceeds"):
        LoopObservation("loop-1", 1, "task-1", True, "news", "x" * 1801)
