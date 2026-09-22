from __future__ import annotations

from core.agent_runtime import RuntimeReport
from core.control_tower import ControlTower, _report_evidence
from core.creator_critic_runtime import build_creator_critic_loop


def test_control_tower_failure_generates_and_evaluates_bounded_proposal() -> None:
    calls: list[str] = []

    def fake_model(prompt: str) -> str:
        calls.append(prompt)
        return "Minimal test-backed improvement proposal."

    tower = ControlTower(creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1))
    decision = tower.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1),
        objective="reduce autonomous test failures",
    )

    assert decision.proposal is not None
    assert decision.proposal.task is not None
    assert len(decision.duel) == 1
    assert decision.duel[0].evaluation.passed is False
    assert decision.approved_for_pipeline is False
    assert decision.approved_task is None
    assert len(calls) == 2


def test_control_tower_approved_task_is_exposed_only_after_pass() -> None:
    def fake_model(_prompt: str) -> str:
        return "Minimal test-backed improvement proposal."

    engine = SelfImprovementEngine()
    failed = RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1)
    engine.observe(failed)
    tower = ControlTower(
        feedback_engine=engine,
        creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1),
    )
    decision = tower.evaluate_proposal(
        RuntimeReport((), rounds=1, integration_ready=True),
        engine.propose(),
        objective="repair the test failure",
        evidence={"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0},
    )

    assert decision.approved_for_pipeline is True
    assert decision.approved_task == decision.proposal.task


def test_control_tower_does_not_run_creator_critic_without_proposal() -> None:
    called = False

    def fake_model(_prompt: str) -> str:
        nonlocal called
        called = True
        return "should not run"

    tower = ControlTower(creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1))
    decision = tower.observe(RuntimeReport((), rounds=1, integration_ready=True))

    assert decision.proposal is None
    assert decision.duel == ()
    assert called is False


def test_report_evidence_fails_closed_and_accepts_explicit_measurements() -> None:
    failed = RuntimeReport((), failed_task_id="t1", error="boom", rounds=1)
    evidence = _report_evidence(failed, {"accuracy": 0.9})

    assert evidence["safety"] == 0.0
    assert evidence["accuracy"] == 0.9
    assert evidence["integration_ready"] is False


def test_report_evidence_cannot_override_runtime_safety_facts() -> None:
    failed = RuntimeReport((), failed_task_id="t1", error="boom", rounds=2, repair_attempts=1)
    evidence = _report_evidence(
        failed,
        {
            "safety": 1.0,
            "runtime_success": True,
            "integration_ready": True,
            "rounds": 99,
            "repair_attempts": 0,
            "accuracy": 0.9,
        },
    )

    assert evidence["safety"] == 0.0
    assert evidence["runtime_success"] is False
    assert evidence["integration_ready"] is False
    assert evidence["rounds"] == 2
    assert evidence["repair_attempts"] == 1
    assert evidence["accuracy"] == 0.9
