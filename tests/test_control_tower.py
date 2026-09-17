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

    tower = ControlTower(creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1))
    decision = tower.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1),
        objective="repair the test failure",
        candidate_evidence_provider=lambda candidate: {
            "accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0,
            "candidate_test": f"evaluated:{candidate.candidate_id}",
        },
    )

    assert decision.approved_for_pipeline is True
    assert decision.approved_task == decision.proposal.task



def test_control_tower_does_not_approve_from_static_runtime_evidence() -> None:
    def fake_model(_prompt: str) -> str:
        return "proposal"

    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1)
    )
    decision = tower.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1),
        objective="repair the test failure",
        evidence={"accuracy": 1.0, "stability": 1.0, "efficiency": 1.0, "safety": 1.0},
    )

    assert decision.proposal is not None
    assert decision.duel == ()
    assert decision.approved_for_pipeline is False
    assert decision.approved_task is None



def test_control_tower_fails_closed_when_candidate_evidence_provider_errors() -> None:
    def fake_model(_prompt: str) -> str:
        return "proposal"

    def failing_evidence(_candidate) -> dict[str, object]:
        raise RuntimeError("sandbox unavailable")

    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1)
    )
    decision = tower.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1),
        objective="repair the test failure",
        candidate_evidence_provider=failing_evidence,
    )

    assert decision.approved_for_pipeline is False
    assert decision.approved_task is None
    assert decision.evaluation_error is not None
    assert "sandbox unavailable" in decision.evaluation_error


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
