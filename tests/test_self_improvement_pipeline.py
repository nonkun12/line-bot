from __future__ import annotations

from core.agent_runtime import MultiAgentRuntime, RuntimeReport
from core.control_tower import ControlTower
from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop
from core.multi_agent import AgentRole, AgentTask
from core.self_improvement import SelfImprovementEngine


class SpyExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task: AgentTask):
        self.calls.append(task.task_id)
        raise AssertionError("approved self-improvement task must not execute automatically")


def test_approved_self_improvement_task_is_exposed_but_not_executed() -> None:
    engine = SelfImprovementEngine()
    engine.observe(RuntimeReport((), failed_task_id="test", error="pytest failed", rounds=1))
    tower = ControlTower(
        feedback_engine=engine,
        creator_critic=CreatorCriticLoop(
            CreatorAgent(lambda prompt: "bounded improvement proposal"),
            CriticAgent(lambda prompt: "evidence supports the bounded proposal"),
        ),
    )
    spy = SpyExecutor()
    runtime = MultiAgentRuntime({AgentRole.DEBUGGER: spy}, control_tower=tower)

    report = RuntimeReport((), rounds=1, integration_ready=True)
    decision = runtime.run_self_improvement_cycle(
        report,
        objective="reduce repeated autonomous test failures",
        evidence={
            "accuracy": 0.9,
            "stability": 0.9,
            "efficiency": 0.8,
            "safety": 1.0,
        },
    )

    assert decision is runtime.last_control_tower_decision
    assert decision is not None
    assert decision.approved_for_pipeline
    assert decision.approved_task is not None
    assert decision.approved_task.role is AgentRole.DEBUGGER
    assert spy.calls == []
