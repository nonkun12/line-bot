from __future__ import annotations

from core.agents import AgentRequest
from core.management_ai import ManagementPlan, ManagementPlanner
from core.management_bridge import run_management_request
from core.management_contract import ManagementDecision, ManagementRequest
from core.multi_agent import AgentRole, AgentTask
from core.multi_agent import AgentResult


class DriftedPlanner(ManagementPlanner):
    def plan(
        self,
        request: ManagementRequest,
        decision: ManagementDecision,
        feedback=(),
    ) -> ManagementPlan:
        return ManagementPlan(
            objective="combined lookup",
            decision=decision,
            tasks=(
                AgentTask(
                    "news-task",
                    AgentRole.NEWS,
                    "Collect the latest news articles and summaries.",
                    resources=frozenset({"news"}),
                ),
                AgentTask(
                    "stocks-task",
                    AgentRole.STOCKS,
                    "Use SYMBOL for the requested quote.",
                    resources=frozenset({"stocks"}),
                ),
                AgentTask(
                    "general-task",
                    AgentRole.GENERAL,
                    "Provide a generic summary.",
                    resources=frozenset({"general"}),
                ),
            ),
        )


class CapturingExecutor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role
        self.instructions: list[str] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.instructions.append(task.instruction)
        return AgentResult(task.task_id, True, f"{self.role.value} result")


def test_management_data_tasks_are_bound_to_user_source(monkeypatch) -> None:
    news = CapturingExecutor(AgentRole.NEWS)
    stocks = CapturingExecutor(AgentRole.STOCKS)
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: news,
            AgentRole.STOCKS: stocks,
        },
    )

    reply = run_management_request(
        "u1",
        "AI NEWSと7203の株価を調べて",
        channel="line",
        planner=DriftedPlanner(),
    )

    assert reply == "【AI NEWS】\nnews result\n\n【Stocks】\nstocks result"
    assert news.instructions == ["AI NEWS"]
    assert stocks.instructions == ["ticker 7203.T"]
