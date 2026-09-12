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


def development_tasks() -> list[AgentTask]:
    return [
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
        task("review", AgentRole.REVIEWER, ("test",)),
        task("integrate", AgentRole.INTEGRATOR, ("review",)),
    ]


def development_runtime(executor: object | None = None) -> MultiAgentRuntime:
    shared = executor or Executor({})
    return MultiAgentRuntime({
        AgentRole.IMPLEMENTER: shared,
        AgentRole.TESTER: shared,
        AgentRole.REVIEWER: shared,
        AgentRole.REPAIRER: shared,
        AgentRole.INTEGRATOR: shared,
    })


def test_static_runtime_runs_dependency_order() -> None:
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({}),
    })
    report = runtime.run([
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
    ])
    assert report.success
    assert [x.task.task_id for x in report.completed] == ["implement", "test"]


def test_static_runtime_fails_closed_on_missing_executor() -> None:
    runtime = MultiAgentRuntime({AgentRole.IMPLEMENTER: Executor({})})
    report = runtime.run([task("test", AgentRole.TESTER)])
    assert not report.success
    assert report.failed_task_id == "test"
    assert report.completed == ()


@pytest.mark.parametrize("mode", ["raise", "wrong_type", "wrong_task_id"])
def test_static_runtime_fails_closed_on_bad_executor(mode: str) -> None:
    class BadExecutor:
        def execute(self, t: AgentTask) -> object:
            if mode == "raise":
                raise RuntimeError("provider timeout")
            if mode == "wrong_type":
                return "not-an-agent-result"
            return AgentResult("different-task", True, "bad")

    runtime = MultiAgentRuntime({AgentRole.TESTER: BadExecutor()})
    report = runtime.run([task("test", AgentRole.TESTER)])
    assert not report.success
    assert report.failed_task_id == "test"
    assert report.error is not None
    assert report.completed == ()


def test_development_loop_retests_reviews_and_runs_integrator_after_test_failure() -> None:
    calls: list[str] = []
    test_attempts = 0

    class Sequenced:
        def execute(self, t: AgentTask) -> AgentResult:
            nonlocal test_attempts
            calls.append(t.task_id)
            if t.role is AgentRole.TESTER:
                test_attempts += 1
                if test_attempts == 1:
                    return AgentResult(t.task_id, False, "pytest failed")
            return AgentResult(t.task_id, True, "ok")

    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Sequenced(),
        AgentRole.TESTER: Sequenced(),
        AgentRole.REVIEWER: Sequenced(),
        AgentRole.REPAIRER: Sequenced(),
        AgentRole.INTEGRATOR: Sequenced(),
    }, max_workers=1, max_rounds=3)
    report = runtime.run_development(development_tasks(), repair_planner=Repair())

    assert report.success
    assert report.integration_ready
    assert report.repair_attempts == 1
    assert "repair-1" in calls
    assert any(call.startswith("test:retest1") for call in calls)
    assert any(call.startswith("test:review1") for call in calls)
    assert any(call.startswith("integrate:gate1") for call in calls)


def test_development_loop_requires_reviewer_and_integrator_tasks() -> None:
    runtime = development_runtime()
    report = runtime.run_development([
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
        task("review", AgentRole.REVIEWER, ("test",)),
    ])
    assert not report.success
    assert report.error == "required development role missing: integrator"
    assert not report.integration_ready


def test_development_loop_rejects_missing_reviewer() -> None:
    runtime = development_runtime()
    report = runtime.run_development([
        task("implement", AgentRole.IMPLEMENTER),
        task("test", AgentRole.TESTER, ("implement",)),
        task("integrate", AgentRole.INTEGRATOR, ("test",)),
    ])
    assert not report.success
    assert report.error == "required development role missing: reviewer"
    assert not report.integration_ready


def test_development_loop_reviewer_failure_repairs_retests_rereviews_and_integrates() -> None:
    calls: list[str] = []

    class ReviewerFailsOnce:
        def execute(self, t: AgentTask) -> AgentResult:
            calls.append(t.task_id)
            if t.role is AgentRole.REVIEWER and t.task_id == "review":
                return AgentResult(t.task_id, False, "review failed")
            return AgentResult(t.task_id, True, "ok")

    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: ReviewerFailsOnce(),
        AgentRole.TESTER: ReviewerFailsOnce(),
        AgentRole.REVIEWER: ReviewerFailsOnce(),
        AgentRole.REPAIRER: ReviewerFailsOnce(),
        AgentRole.INTEGRATOR: ReviewerFailsOnce(),
    })
    report = runtime.run_development(development_tasks(), repair_planner=Repair())
    assert report.success
    assert report.integration_ready
    assert any(call.startswith("review:retest1") for call in calls)
    assert any(call.startswith("review:rereview1") for call in calls)
    assert any(call.startswith("integrate:gate1") for call in calls)


def test_repair_failure_is_reported_without_follow_up() -> None:
    class FailRepair:
        def execute(self, t: AgentTask) -> AgentResult:
            if t.role is AgentRole.TESTER:
                return AgentResult(t.task_id, False, "pytest failed")
            if t.role is AgentRole.REPAIRER:
                return AgentResult(t.task_id, False, "repair failed")
            return AgentResult(t.task_id, True, "ok")

    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: FailRepair(),
        AgentRole.TESTER: FailRepair(),
        AgentRole.REVIEWER: FailRepair(),
        AgentRole.REPAIRER: FailRepair(),
        AgentRole.INTEGRATOR: FailRepair(),
    })
    report = runtime.run_development(development_tasks(), repair_planner=Repair())
    assert not report.success
    assert report.failed_task_id == "repair-1"
    assert report.error == "repair failed"


def test_round_limit_is_bounded() -> None:
    class AlwaysFail:
        def execute(self, t: AgentTask) -> AgentResult:
            if t.role is AgentRole.REPAIRER:
                return AgentResult(t.task_id, True, "repaired")
            return AgentResult(t.task_id, False, "still broken")

    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: AlwaysFail(),
        AgentRole.TESTER: AlwaysFail(),
        AgentRole.REVIEWER: AlwaysFail(),
        AgentRole.REPAIRER: AlwaysFail(),
        AgentRole.INTEGRATOR: AlwaysFail(),
    }, max_rounds=3)
    report = runtime.run_development(development_tasks(), repair_planner=Repair())
    assert not report.success
    assert report.rounds <= 3
    assert report.repair_attempts <= 2


def test_max_rounds_cannot_be_unbounded() -> None:
    with pytest.raises(ValueError):
        MultiAgentRuntime({}, max_rounds=4)


def test_parallel_workers_are_rejected_until_worktree_isolation() -> None:
    with pytest.raises(ValueError, match="isolated git worktrees"):
        MultiAgentRuntime({}, max_workers=2)
