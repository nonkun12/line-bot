from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.agent_runtime import MultiAgentRuntime
from core.multi_agent import AgentResult, AgentRole, AgentTask


@dataclass
class Executor:
    outcomes: dict[str, AgentResult]

    def execute(self, task: AgentTask) -> AgentResult:
        return self.outcomes.get(task.task_id, AgentResult(task.task_id, True, "ok"))


class Repair:
    def repair_task(self, failed_task: AgentTask, result: AgentResult, attempt: int) -> AgentTask:
        return AgentTask(
            task_id=f"repair-{attempt}",
            role=AgentRole.REPAIRER,
            instruction=f"Repair {failed_task.task_id}",
            resources=failed_task.resources,
        )


def task(task_id: str, role: AgentRole, deps: tuple[str, ...] = ()) -> AgentTask:
    return AgentTask(task_id, role, task_id, frozenset({"src/a.py"}), deps)


def test_static_runtime_runs_dependency_order() -> None:
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({}),
    })
    report = runtime.run([task("implement", AgentRole.IMPLEMENTER),
                         task("test", AgentRole.TESTER, ("implement",))])
    assert report.success
    assert [x.task.task_id for x in report.completed] == ["implement", "test"]


def test_static_runtime_fails_closed_on_missing_executor() -> None:
    runtime = MultiAgentRuntime({AgentRole.IMPLEMENTER: Executor({})})
    report = runtime.run([task("test", AgentRole.TESTER)])
    assert not report.success
    assert report.failed_task_id == "test"
    assert report.completed == ()


def test_development_loop_retests_and_reviews_after_test_failure() -> None:
    calls: list[str] = []

    class Sequenced:
        def execute(self, t: AgentTask) -> AgentResult:
            calls.append(t.task_id)
            if t.task_id == "test":
                return AgentResult(t.task_id, False, "pytest failed")
            return AgentResult(t.task_id, True, "ok")

    # The initial failure is deliberately repaired, and the replacement test/review pass.
    class RepairThenPass:
        def execute(self, t: AgentTask) -> AgentResult:
            calls.append(t.task_id)
            return AgentResult(t.task_id, True, "ok")

    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Sequenced(),
        AgentRole.TESTER: Sequenced(),
        AgentRole.REVIEWER: Sequenced(),
        AgentRole.REPAIRER: RepairThenPass(),
    }, max_workers=1, max_rounds=3)
    report = runtime.run_development([
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
        task("review", AgentRole.REVIEWER, ("test",)),
    ], repair_planner=Repair())

    assert report.success
    assert report.integration_ready
    assert report.repair_attempts == 1
    assert "repair-1" in calls
    assert "test:retest" in calls
    assert "test:review" in calls


def test_development_loop_requires_reviewer_gate() -> None:
    runtime = MultiAgentRuntime({AgentRole.IMPLEMENTER: Executor({}), AgentRole.TESTER: Executor({})})
    report = runtime.run_development([
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
    ])
    assert not report.success
    assert report.error == "reviewer gate missing"
    assert not report.integration_ready


def test_round_limit_is_bounded() -> None:
    class AlwaysFail:
        def execute(self, t: AgentTask) -> AgentResult:
            return AgentResult(t.task_id, False, "still broken")

    runtime = MultiAgentRuntime({AgentRole.TESTER: AlwaysFail(), AgentRole.REPAIRER: Executor({})}, max_rounds=3)
    report = runtime.run_development([task("test", AgentRole.TESTER)], repair_planner=Repair())
    assert not report.success
    assert report.rounds <= 3
    assert report.repair_attempts <= 2


def test_max_rounds_cannot_be_unbounded() -> None:
    with pytest.raises(ValueError):
        MultiAgentRuntime({}, max_rounds=4)
