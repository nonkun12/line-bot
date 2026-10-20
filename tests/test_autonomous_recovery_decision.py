from scripts.autonomous_recovery_decision import (
    RecoveryAction,
    RecoveryClass,
    decide_recovery,
)


def test_missing_run_allows_only_one_task_recovery():
    result = decide_recovery(run_status=None)
    assert result.classification == RecoveryClass.MISSING_RUN
    assert result.action == RecoveryAction.DISPATCH_ONE_TASK


def test_active_run_prevents_dispatch():
    result = decide_recovery(run_status=None, another_run_active=True)
    assert result.classification == RecoveryClass.RUN_STILL_ACTIVE
    assert result.action == RecoveryAction.NO_ACTION


def test_queued_run_prevents_dispatch():
    result = decide_recovery(run_status="queued")
    assert result.classification == RecoveryClass.RUN_STILL_ACTIVE
    assert result.action == RecoveryAction.NO_ACTION


def test_same_slot_is_never_dispatched_twice():
    result = decide_recovery(run_status=None, slot_already_dispatched=True)
    assert result.classification == RecoveryClass.DUPLICATE_SLOT
    assert result.action == RecoveryAction.NO_ACTION


def test_api_or_audit_failure_fails_closed():
    result = decide_recovery(run_status=None, evidence_available=False)
    assert result.classification == RecoveryClass.AUDIT_UNAVAILABLE
    assert result.action == RecoveryAction.BLOCK


def test_empty_queue_is_not_treated_as_failure_to_retry():
    result = decide_recovery(run_status="completed", run_conclusion="success", task_id="QUEUE_EMPTY")
    assert result.classification == RecoveryClass.QUEUE_EMPTY
    assert result.action == RecoveryAction.NO_ACTION


def test_exhausted_queue_alias_is_classified_as_empty():
    result = decide_recovery(
        run_status="completed",
        run_conclusion="success",
        task_id="QUEUE_EXHAUSTED_NO_TASKS",
    )
    assert result.classification == RecoveryClass.QUEUE_EMPTY
    assert result.action == RecoveryAction.NO_ACTION


def test_not_run_is_not_retried():
    result = decide_recovery(run_status="completed", run_conclusion="success", task_id="NOT_RUN")
    assert result.classification == RecoveryClass.NOT_RUN
    assert result.action == RecoveryAction.NO_ACTION


def test_failed_workflow_is_not_blindly_retried():
    result = decide_recovery(run_status="completed", run_conclusion="failure")
    assert result.classification == RecoveryClass.WORKFLOW_FAILED
    assert result.action == RecoveryAction.BLOCK


def test_held_task_needs_explicit_cause_fix_path():
    result = decide_recovery(
        run_status="completed", run_conclusion="success", task_id="task-123",
        safety_gate="PASS", verification="PASS", tests="PASS", held=True,
    )
    assert result.classification == RecoveryClass.BLOCKED_HELD
    assert result.action == RecoveryAction.BLOCK


def test_safety_gate_failure_blocks():
    result = decide_recovery(
        run_status="completed", run_conclusion="success", task_id="task-123",
        safety_gate="FAIL", verification="PASS", tests="PASS",
    )
    assert result.action == RecoveryAction.BLOCK


def test_test_failure_blocks_without_retry():
    result = decide_recovery(
        run_status="completed", run_conclusion="success", task_id="task-123",
        safety_gate="PASS", verification="PASS", tests="FAIL",
    )
    assert result.classification == RecoveryClass.TASK_FAILED
    assert result.action == RecoveryAction.BLOCK


def test_verified_success_does_not_dispatch():
    result = decide_recovery(
        run_status="completed", run_conclusion="success", task_id="task-123",
        safety_gate="PASS", verification="PASS", tests="PASS",
    )
    assert result.classification == RecoveryClass.VERIFIED_SUCCESS
    assert result.action == RecoveryAction.NO_ACTION


def test_unknown_status_fails_closed():
    result = decide_recovery(run_status="unknown")
    assert result.classification == RecoveryClass.AUDIT_UNAVAILABLE
    assert result.action == RecoveryAction.BLOCK
