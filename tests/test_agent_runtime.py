from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.agent_runtime import MultiAgentRuntime, RuntimeReport
from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.control_tower import ControlTower
from core.self_improvement import SelfImprovementEngine


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


def test_runtime_development_emits_final_report_to_feedback_engine() -> None:
    engine = SelfImprovementEngine()
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({}),
        AgentRole.REVIEWER: Executor({}),
        AgentRole.REPAIRER: Executor({}),
        AgentRole.INTEGRATOR: Executor({}),
    }, feedback_engine=engine)

    report = runtime.run_development(development_tasks())

    assert report.success
    assert report.integration_ready
    assert [signal.kind for signal in engine.signals] == ["success"]


def test_runtime_failure_emits_debug_signal_to_feedback_engine() -> None:
    engine = SelfImprovementEngine()
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({"test": AgentResult("test", False, "pytest failed")}),
        AgentRole.REVIEWER: Executor({}),
        AgentRole.REPAIRER: Executor({}),
        AgentRole.INTEGRATOR: Executor({}),
    }, feedback_engine=engine)

    report = runtime.run_development(development_tasks())

    assert not report.success
    assert engine.signals[-1].kind == "failure"
    assert engine.propose() is not None


def test_runtime_persists_self_improvement_cycle_without_executing_proposal(tmp_path) -> None:
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({"test": AgentResult("test", False, "pytest failed")}),
        AgentRole.REVIEWER: Executor({}),
        AgentRole.REPAIRER: Executor({}),
        AgentRole.INTEGRATOR: Executor({}),
    }, self_improvement_history_path=tmp_path / "self-improvement.jsonl",
       self_improvement_target_paths=("tests/test_agent_runtime.py",))

    first = runtime.run_development(development_tasks())
    second = runtime.run_development(development_tasks())

    assert not first.success
    assert not second.success
    assert runtime.last_self_improvement_cycle is not None
    assert len(runtime.last_self_improvement_cycle.proposals) >= 1
    assert runtime.last_self_improvement_cycle.proposals[0].task is not None
    assert runtime.last_self_improvement_cycle_error is None


def test_runtime_self_improvement_cycle_exposes_reviewed_decision_without_mutation() -> None:
    model = lambda prompt: "minimal test-backed improvement"
    critic = lambda prompt: "evidence supports the bounded proposal"
    engine = SelfImprovementEngine()
    engine.observe(RuntimeReport((), failed_task_id="test", error="pytest failed", rounds=1))
    tower = ControlTower(
        feedback_engine=engine,
        creator_critic=CreatorCriticLoop(CreatorAgent(model), CriticAgent(critic)),
    )
    runtime = development_runtime()
    runtime._control_tower = tower

    report = RuntimeReport((), rounds=1, integration_ready=True)
    decision = runtime.run_self_improvement_cycle(
        report,
        objective="reduce repeated autonomous test failures",
        evidence={"accuracy": 0.9, "stability": 0.9, "efficiency": 0.8, "safety": 1.0},
    )

    assert decision is runtime.last_control_tower_decision
    assert decision is not None
    assert decision.proposal is not None
    assert decision.approved_for_pipeline
    assert decision.approved_task is not None
    assert decision.approved_task.role is AgentRole.DEBUGGER


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


def test_control_tower_receives_final_success_report() -> None:
    class Tower:
        def __init__(self) -> None:
            self.reports = []

        def observe(self, report: object) -> object:
            self.reports.append(report)
            return object()

    tower = Tower()
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({}),
        AgentRole.REVIEWER: Executor({}),
        AgentRole.REPAIRER: Executor({}),
        AgentRole.INTEGRATOR: Executor({}),
    }, control_tower=tower)

    report = runtime.run_development(development_tasks())

    assert report.success and report.integration_ready
    assert tower.reports == [report]


def test_control_tower_is_the_single_observer_when_both_are_supplied() -> None:
    engine = SelfImprovementEngine()

    class Tower:
        def __init__(self) -> None:
            self.feedback_engine = engine
            self.reports = []

        def observe(self, report: object) -> object:
            self.reports.append(report)
            return object()

    tower = Tower()
    runtime = MultiAgentRuntime({
        AgentRole.IMPLEMENTER: Executor({}),
        AgentRole.TESTER: Executor({}),
        AgentRole.REVIEWER: Executor({}),
        AgentRole.REPAIRER: Executor({}),
        AgentRole.INTEGRATOR: Executor({}),
    }, feedback_engine=engine, control_tower=tower)

    report = runtime.run_development(development_tasks())

    assert report.success
    assert tower.reports == [report]
    assert engine.signals == ()


def test_control_tower_and_different_feedback_engine_are_rejected() -> None:
    engine = SelfImprovementEngine()

    class Tower:
        feedback_engine = SelfImprovementEngine()

    with pytest.raises(ValueError, match="share the same feedback engine"):
        MultiAgentRuntime({}, feedback_engine=engine, control_tower=Tower())


def test_execution_safety_gate_fails_closed_on_rejected_worktree():
    from core.agent_runtime import MultiAgentRuntime, RuntimeExecutionError

    class Executor:
        def execute(self, task):
            from core.multi_agent import AgentResult
            return AgentResult(task_id=task.task_id, success=True)

    class Gate:
        def verify(self, task, result, allowed_paths):
            return False

    runtime = MultiAgentRuntime({AgentRole.IMPLEMENTER: Executor()})
    runtime.set_execution_safety_gate(Gate())
    report = runtime.run((
        AgentTask(
            task_id="impl",
            role=AgentRole.IMPLEMENTER,
            instruction="implement",
            resources=frozenset({"runtime"}),
        ),
    ))
    assert report.success is False
    assert report.failed_task_id == "impl"
    assert "safety gate rejected" in (report.error or "")


def test_control_tower_approval_is_bound_to_exact_task():
    model = lambda prompt: "bounded proposal"
    critic = lambda prompt: "evidence supports the proposal"
    engine = SelfImprovementEngine()
    failed_report = RuntimeReport((), failed_task_id="test", error="pytest failed", rounds=1)
    engine.observe(failed_report)
    tower = ControlTower(
        feedback_engine=engine,
        creator_critic=CreatorCriticLoop(CreatorAgent(model), CriticAgent(critic)),
    )
    report = RuntimeReport((), rounds=1, integration_ready=True)
    proposal = tower.feedback_engine.propose()
    assert proposal is not None

    decision = tower.evaluate_proposal(report, proposal, evidence={
        "accuracy": 0.9,
        "stability": 0.9,
        "efficiency": 0.8,
        "safety": 1.0,
    })
    assert decision.approved_for_pipeline
    approved = decision.approved_task
    assert approved is not None

    tampered = AgentTask(
        task_id=approved.task_id,
        role=approved.role,
        instruction=approved.instruction + " with widened scope",
        resources=approved.resources,
        depends_on=approved.depends_on,
        priority=approved.priority,
    )
    assert decision.approved_task_matches(approved)
    assert not decision.approved_task_matches(tampered)
    assert decision.approved_task is approved



def test_runtime_claims_approved_handoff_once(tmp_path):
    from core.agent_runtime import MultiAgentRuntime
    from core.control_tower import task_hash
    from core.self_improvement_handoff import ApprovedImprovementHandoff

    task = AgentTask(
        "self-improvement:claim-test",
        AgentRole.DEBUGGER,
        "Investigate recurring failure.",
        frozenset({"runtime"}),
    )
    handoff = ApprovedImprovementHandoff(
        task=task,
        task_hash=task_hash(task) or "",
        allowed_paths=("tests/test_agent_runtime.py",),
    )
    runtime = MultiAgentRuntime(
        {},
        self_improvement_handoff_claim_path=tmp_path / "claims.jsonl",
    )

    assert runtime.claim_self_improvement_handoff(handoff) is True
    assert runtime.claim_self_improvement_handoff(handoff) is False
    assert runtime.is_self_improvement_handoff_claimed(handoff) is True


def test_runtime_claim_requires_explicit_claim_store(tmp_path):
    from core.agent_runtime import MultiAgentRuntime
    from core.control_tower import task_hash
    from core.self_improvement_handoff import ApprovedImprovementHandoff

    task = AgentTask(
        "self-improvement:no-store",
        AgentRole.DEBUGGER,
        "Investigate recurring failure.",
        frozenset({"runtime"}),
    )
    handoff = ApprovedImprovementHandoff(
        task=task,
        task_hash=task_hash(task) or "",
        allowed_paths=("tests/test_agent_runtime.py",),
    )
    runtime = MultiAgentRuntime({})

    with pytest.raises(RuntimeError, match="claim store is not configured"):
        runtime.claim_self_improvement_handoff(handoff)
