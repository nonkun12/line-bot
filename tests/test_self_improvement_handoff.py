from core.control_tower import ControlTower, ControlTowerDecision
from core.creator_critic_runtime import build_creator_critic_loop
from core.self_improvement import ImprovementProposal
from core.self_improvement_handoff import build_approved_improvement_handoff
from core.self_improvement import ImprovementSignal
from core.multi_agent import AgentRole, AgentTask
from core.agent_runtime import RuntimeReport


def _approved_decision():
    model = lambda _prompt: "bounded test-backed improvement"
    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=model, max_iterations=1)
    )
    task = AgentTask(
        task_id="self-improvement:debug",
        role=AgentRole.DEBUGGER,
        instruction="Investigate recurring failure and add a regression test.",
        resources=frozenset({"tests"}),
        priority=1,
    )
    proposal = ImprovementProposal(
        "Investigate recurring failure",
        "Observed recurring failure.",
        (ImprovementSignal("failure", "tests", "timeout"),),
        task,
    )
    report = RuntimeReport(
        (),
        rounds=1,
        integration_ready=True,
    )
    decision = tower.evaluate_proposal(
        report,
        proposal,
        evidence={"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0},
    )
    assert decision.approved_for_pipeline
    return decision


def test_handoff_is_immutable_and_exact():
    decision = _approved_decision()
    handoff = build_approved_improvement_handoff(
        decision,
        ("tests/test_runtime.py",),
    )

    assert handoff.task is decision.approved_task
    assert handoff.task_hash == decision.approved_task_hash
    assert handoff.allowed_paths == ("tests/test_runtime.py",)


def test_handoff_rejects_unapproved_decision():
    task = AgentTask("debug", AgentRole.DEBUGGER, "bounded fix", frozenset({"tests"}))
    proposal = ImprovementProposal("title", "reason", (), task)
    decision = ControlTowerDecision((), proposal)

    try:
        build_approved_improvement_handoff(decision, ("tests/test_runtime.py",))
    except PermissionError as exc:
        assert str(exc) == "self-improvement proposal is not approved for pipeline"
    else:
        raise AssertionError("expected PermissionError")


def test_handoff_rejects_protected_targets():
    decision = _approved_decision()
    try:
        build_approved_improvement_handoff(decision, ("core/self_improvement_policy.py",))
    except PermissionError as exc:
        assert "explicit_approval" in str(exc)
    else:
        raise AssertionError("expected PermissionError")


def test_handoff_rejects_role_escalation():
    model = lambda _prompt: "bounded improvement"
    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=model, max_iterations=1)
    )
    task = AgentTask("self-improvement:wrong-role", AgentRole.IMPLEMENTER, "mutate", frozenset({"tests"}))
    proposal = ImprovementProposal("title", "reason", (), task)
    report = RuntimeReport((), rounds=1, integration_ready=True)
    decision = tower.evaluate_proposal(
        report,
        proposal,
        evidence={"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0},
    )

    assert decision.approved_for_pipeline
    try:
        build_approved_improvement_handoff(decision, ("tests/test_runtime.py",))
    except PermissionError as exc:
        assert str(exc) == "only bounded debugger tasks may enter self-improvement handoff"
    else:
        raise AssertionError("expected PermissionError")
