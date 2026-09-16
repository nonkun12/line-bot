import pytest

from core.control_tower import ControlTower
from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop
from core.distributed_runtime import DistributedDevelopmentCoordinator
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.self_improvement import SelfImprovementEngine


class Executor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role
        self.calls: list[str] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls.append(task.task_id)
        return AgentResult(task.task_id, True, f"{self.role.value} completed")


def make_task(task_id: str, role: AgentRole, *, depends_on=()) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        role=role,
        instruction=task_id,
        depends_on=tuple(depends_on),
    )


def test_coordinator_defaults_to_serialized_execution_and_reports_success() -> None:
    manager = Executor(AgentRole.MANAGER)
    tester = Executor(AgentRole.TESTER)
    coordinator = DistributedDevelopmentCoordinator(
        {AgentRole.MANAGER: manager, AgentRole.TESTER: tester}
    )

    result = coordinator.run(
        (
            make_task("manager", AgentRole.MANAGER),
            make_task("tester", AgentRole.TESTER, depends_on=("manager",)),
        )
    )

    assert coordinator.max_workers == 1
    assert result.report.success
    assert result.report.integration_ready
    assert [item.task.task_id for item in result.report.completed] == ["manager", "tester"]
    assert result.decision is None


def test_parallel_execution_requires_explicit_isolation() -> None:
    with pytest.raises(ValueError, match="isolated=True"):
        DistributedDevelopmentCoordinator({}, max_workers=2)

    coordinator = DistributedDevelopmentCoordinator({}, max_workers=2, isolated=True)
    assert coordinator.max_workers == 2


def test_coordinator_observes_control_tower_but_does_not_execute_approval() -> None:
    manager = Executor(AgentRole.MANAGER)
    tower = ControlTower(
        feedback_engine=SelfImprovementEngine(),
        creator_critic=CreatorCriticLoop(
            CreatorAgent(lambda prompt: "bounded improvement proposal"),
            CriticAgent(lambda prompt: "evidence supports the bounded proposal"),
        ),
    )
    coordinator = DistributedDevelopmentCoordinator(
        {AgentRole.MANAGER: manager},
        control_tower=tower,
    )

    result = coordinator.run(
        (make_task("manager", AgentRole.MANAGER),),
        objective="reduce repeated autonomous test failures",
        evidence={
            "accuracy": 0.9,
            "stability": 0.9,
            "efficiency": 0.8,
            "safety": 1.0,
        },
    )

    assert result.report.success
    assert result.decision is not None
    assert manager.calls == ["manager"]
    assert result.decision.approved_task is not None
    assert result.decision.approved_task.role is AgentRole.DEBUGGER
    assert manager.calls == ["manager"]
