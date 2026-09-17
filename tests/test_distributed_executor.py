from __future__ import annotations

from core.distributed_executor import AgentPromptPolicy, DistributedAIExecutor
from core.distributed_runtime import DistributedDevelopmentCoordinator
from core.multi_agent import AgentRole, AgentTask


def test_executor_returns_model_text_without_granting_mutation_capabilities() -> None:
    prompts: list[str] = []

    def fake_model(prompt: str) -> str:
        prompts.append(prompt)
        return "analysis complete"

    executor = DistributedAIExecutor(model_call=fake_model)
    task = AgentTask(
        "manager-1",
        AgentRole.MANAGER,
        "Break down the requested feature.",
        resources=frozenset({"planning"}),
    )

    result = executor.execute(task)

    assert result.success
    assert result.task_id == "manager-1"
    assert result.summary == "analysis complete"
    assert result.changed_resources == frozenset()
    assert "Role: manager" in prompts[0]
    assert "shell commands" in prompts[0]
    assert "Break down the requested feature." in prompts[0]


def test_executor_fails_closed_when_model_call_raises() -> None:
    def failing_model(prompt: str) -> str:
        raise RuntimeError("provider unavailable")

    result = DistributedAIExecutor(model_call=failing_model).execute(
        AgentTask("tester-1", AgentRole.TESTER, "Analyze the test strategy.")
    )

    assert not result.success
    assert result.task_id == "tester-1"
    assert "provider unavailable" in result.summary
    assert result.changed_resources == frozenset()


def test_executor_respects_explicit_role_allowlist() -> None:
    calls = 0

    def fake_model(prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    executor = DistributedAIExecutor(
        model_call=fake_model,
        allowed_roles={AgentRole.TESTER: True},
    )

    denied = executor.execute(AgentTask("manager-1", AgentRole.MANAGER, "plan"))
    allowed = executor.execute(AgentTask("tester-1", AgentRole.TESTER, "test"))

    assert not denied.success
    assert denied.changed_resources == frozenset()
    assert allowed.success
    assert calls == 1


def test_scheduler_and_coordinator_can_execute_real_executor_boundary() -> None:
    seen_roles: list[str] = []

    def fake_model(prompt: str) -> str:
        seen_roles.append(prompt.split("Role: ", 1)[1].split("\n", 1)[0])
        return "bounded result"

    executor = DistributedAIExecutor(model_call=fake_model)
    coordinator = DistributedDevelopmentCoordinator(
        {
            AgentRole.MANAGER: executor,
            AgentRole.TESTER: executor,
        }
    )

    result = coordinator.run(
        (
            AgentTask("manager-1", AgentRole.MANAGER, "plan"),
            AgentTask("tester-1", AgentRole.TESTER, "verify", depends_on=("manager-1",)),
        )
    )

    assert result.report.success
    assert result.report.integration_ready
    assert [item.result.summary for item in result.report.completed] == [
        "bounded result",
        "bounded result",
    ]
    assert seen_roles == ["manager", "tester"]


def test_prompt_policy_is_provider_neutral() -> None:
    prompt = AgentPromptPolicy().build(
        AgentTask("review-1", AgentRole.REVIEWER, "Review the proposed change.")
    )

    assert "Role: reviewer" in prompt
    assert "Review the proposed change." in prompt
    assert "file writes" in prompt
