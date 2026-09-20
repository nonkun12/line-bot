from core.agent_runtime import MultiAgentRuntime, RuntimeReport
from core.control_tower import ControlTower
from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop
from core.multi_agent import AgentRole
from core.self_improvement import SelfImprovementEngine


def test_runtime_exposes_approved_immutable_handoff_without_executing_it():
    model = lambda prompt: "bounded proposal"
    critic = lambda prompt: "evidence supports the bounded proposal"
    tower = ControlTower(
        feedback_engine=SelfImprovementEngine(),
        creator_critic=CreatorCriticLoop(CreatorAgent(model), CriticAgent(critic)),
    )
    runtime = MultiAgentRuntime(
        {},
        control_tower=tower,
        self_improvement_target_paths=("tests/test_agent_runtime.py",),
    )

    report = RuntimeReport((), failed_task_id="test", error="pytest failed", rounds=1)
    decision = runtime.run_self_improvement_cycle(
        report,
        objective="reduce repeated autonomous test failures",
        evidence={"accuracy": 0.9, "stability": 0.9, "efficiency": 0.8, "safety": 1.0},
    )

    assert decision is not None
    assert decision.approved_for_pipeline
    assert decision.approved_task is not None
    assert decision.approved_task.role is AgentRole.DEBUGGER

    handoffs = runtime.last_self_improvement_handoffs
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff.task is decision.approved_task
    assert handoff.task_hash == decision.approved_task_hash
    assert handoff.allowed_paths == ("tests/test_agent_runtime.py",)

    try:
        handoff.allowed_paths += ("core/control_tower.py",)
    except Exception:
        pass
    assert handoff.allowed_paths == ("tests/test_agent_runtime.py",)


def test_unapproved_self_improvement_decision_produces_no_handoff():
    tower = ControlTower(feedback_engine=SelfImprovementEngine())
    runtime = MultiAgentRuntime(
        {},
        control_tower=tower,
        self_improvement_target_paths=("tests/test_agent_runtime.py",),
    )

    report = RuntimeReport((), failed_task_id="test", error="pytest failed", rounds=1)
    decision = runtime.run_self_improvement_cycle(report)

    assert decision is not None
    assert decision.approved_for_pipeline is False
    assert runtime.last_self_improvement_handoffs == ()
