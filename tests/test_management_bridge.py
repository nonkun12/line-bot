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


def test_management_bridge_detects_multiple_specialists() -> None:
    roles = specialist_roles_for_message("AIニュースと株価を調べて")
    assert roles == frozenset({AgentRole.NEWS, AgentRole.STOCKS})
    assert should_route_to_management_ai("AIニュースと株価を調べて")


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
