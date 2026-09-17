from __future__ import annotations

from core.agent_runtime import RuntimeReport
from core.control_tower import ControlTower
from core.creator_critic_runtime import build_creator_critic_loop
from core.distributed_executor import DistributedAIExecutor
from core.self_improvement_distributed import DistributedSelfImprovementLoop


def test_distributed_self_improvement_runs_manager_debugger_reviewer_then_control_tower() -> None:
    prompts: list[str] = []

    def fake_model(prompt: str) -> str:
        prompts.append(prompt)
        return "bounded analysis"

    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=fake_model, max_iterations=1)
    )
    loop = DistributedSelfImprovementLoop(
        executor=DistributedAIExecutor(model_call=fake_model),
        control_tower=tower,
    )

    result = loop.run(
        RuntimeReport(
            (),
            failed_task_id="tester-42",
            error="pytest failed",
            rounds=1,
            repair_attempts=1,
        ),
        objective="reduce repeated test failures",
    )

    assert result.analysis_success
    assert [item.task_id for item in result.analysis_results] == [
        "self-improvement:manager",
        "self-improvement:debugger",
        "self-improvement:reviewer",
    ]
    assert result.decision is not None
    assert result.decision.proposal is not None
    assert result.decision.approved_task is None
    assert len(prompts) == 4
    assert any("Role: debugger" in prompt for prompt in prompts)
    assert any("Role: reviewer" in prompt for prompt in prompts)
    assert result.evidence["analysis_success"] is True


def test_distributed_self_improvement_fails_closed_when_analysis_model_fails() -> None:
    calls = 0

    def failing_model(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    tower = ControlTower()
    loop = DistributedSelfImprovementLoop(
        executor=DistributedAIExecutor(model_call=failing_model),
        control_tower=tower,
    )

    result = loop.run(
        RuntimeReport((), failed_task_id="tester-1", error="boom", rounds=1),
        objective="repair failure",
    )

    assert not result.analysis_success
    assert result.decision is None
    assert result.evidence["analysis_success"] is False
    assert "provider unavailable" in result.evidence["analysis_error"]
    assert calls == 2


def test_successful_runtime_does_not_trigger_unnecessary_analysis_calls() -> None:
    called = False

    def fake_model(_prompt: str) -> str:
        nonlocal called
        called = True
        return "unexpected"

    loop = DistributedSelfImprovementLoop(
        executor=DistributedAIExecutor(model_call=fake_model),
        control_tower=ControlTower(),
    )
    result = loop.run(
        RuntimeReport((), rounds=1, integration_ready=True),
        objective="observe success",
    )

    assert result.analysis_success
    assert result.analysis_results == ()
    assert result.decision is None
    assert called is False
