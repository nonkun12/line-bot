from __future__ import annotations

from core.agent_runtime import RuntimeReport, RuntimeTaskResult
from core.control_tower import ControlTower, _report_evidence, task_hash
from core.self_improvement import SelfImprovementEngine
from core.multi_agent import AgentResult, AgentRole, AgentTask
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


def test_control_tower_preserves_proposal_when_reviewer_raises() -> None:
    def broken_model(_prompt: str) -> str:
        raise RuntimeError("provider error may contain sensitive details")

    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=broken_model, max_iterations=1)
    )
    decision = tower.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1),
        objective="reduce autonomous test failures",
    )

    assert decision.proposal is not None
    assert decision.review_error == "RuntimeError"
    assert decision.duel == ()
    assert decision.approved_for_pipeline is False
    assert decision.approved_task is None


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


def test_control_tower_records_runtime_events_without_storing_raw_output() -> None:
    recorded = []

    def recorder(event):
        recorded.append(event)
        return True

    tower = ControlTower(event_recorder=recorder)
    report = RuntimeReport((), failed_task_id="tester-42", error="private failure detail",
                           rounds=2, repair_attempts=1, integration_ready=False)
    tower.observe(report)

    assert len(recorded) == 1
    event = recorded[0]
    assert event.task_id == "tester-42"
    assert event.agent_id == "control_tower"
    assert event.status == "FAILED"
    assert "private failure detail" not in str(event.payload)
    assert event.payload["rounds"] == 2


def test_control_tower_event_store_failure_does_not_change_runtime_result() -> None:
    def broken_recorder(_event):
        raise RuntimeError("sensitive provider detail")

    tower = ControlTower(event_recorder=broken_recorder)
    report = RuntimeReport((), failed_task_id="tester-43", error="test failed", rounds=1)
    decision = tower.observe(report)

    assert decision.proposal is not None
    assert tower.last_event_recording_error == "RuntimeError"



def test_control_tower_does_not_write_to_default_database() -> None:
    tower = ControlTower()
    tower.observe(RuntimeReport((), rounds=1, integration_ready=True))
    assert tower.last_event_recording_error is None


def test_control_tower_uses_unique_run_ids_and_continues_after_record_failure() -> None:
    attempted = []

    def flaky_recorder(event):
        attempted.append(event)
        if len(attempted) == 1:
            raise RuntimeError("db locked")
        return True

    # Reuse completed task records to exercise multiple events in one report.
    from core.multi_agent import AgentRole, AgentTask
    tasks = (
        RuntimeTaskResult(
            AgentTask(task_id="implementer", role=AgentRole.IMPLEMENTER, instruction="x"),
            AgentResult(task_id="implementer", success=True),
        ),
        RuntimeTaskResult(
            AgentTask(task_id="reviewer", role=AgentRole.REVIEWER, instruction="y"),
            AgentResult(task_id="reviewer", success=True),
        ),
    )
    report = RuntimeReport(tasks, rounds=1, integration_ready=True)
    tower = ControlTower(event_recorder=flaky_recorder)
    tower.observe(report)
    assert len(attempted) == 2
    assert attempted[0].event_id != attempted[1].event_id
    assert attempted[0].request_id == attempted[1].request_id
    assert tower.last_event_recording_error == "RuntimeError"


def test_control_tower_records_error_only_runtime_failure() -> None:
    recorded = []
    tower = ControlTower(event_recorder=lambda event: recorded.append(event) or True)
    tower.observe(RuntimeReport((), error="reviewer gate missing", rounds=1))
    assert len(recorded) == 1
    assert recorded[0].role == "control_tower"
    assert recorded[0].status == "FAILED"


def test_control_tower_approved_task_matches_only_the_exact_approved_task() -> None:
    def fake_model(_prompt: str) -> str:
        return "Minimal test-backed improvement proposal."

    engine = SelfImprovementEngine()
    engine.observe(
        RuntimeReport((), failed_task_id="tester-1", error="pytest failed", rounds=1)
    )
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

    approved_task = decision.approved_task
    assert approved_task is not None
    assert decision.approved_task_matches(approved_task) is True
    assert decision.approved_task_matches(None) is False

    modified_task = AgentTask(
        task_id=approved_task.task_id,
        role=approved_task.role,
        instruction=approved_task.instruction + " changed",
        resources=approved_task.resources,
        depends_on=approved_task.depends_on,
        priority=approved_task.priority,
    )
    assert decision.approved_task_matches(modified_task) is False



def test_task_hash_is_stable_sha256_and_handles_missing_task() -> None:
    assert task_hash(None) is None

    task = AgentTask(
        task_id="hash-boundary",
        role=AgentRole.IMPLEMENTER,
        instruction="verify canonical task hashing",
        resources=frozenset({"resource-z", "resource-a"}),
        depends_on=("dependency-2", "dependency-1"),
        priority=7,
    )

    digest = task_hash(task)
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    assert task_hash(task) == digest

    changed_task = AgentTask(
        task_id=task.task_id,
        role=task.role,
        instruction=task.instruction + " changed",
        resources=task.resources,
        depends_on=task.depends_on,
        priority=task.priority,
    )
    assert task_hash(changed_task) != digest
