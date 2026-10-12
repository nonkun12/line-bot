import pytest

from core.loop_execution_contract import (
    ExecutionEvidence,
    ExecutionResult,
    integration_ready,
)


VALID_BASE = "a" * 40
VALID_PRODUCED = "b" * 40


def test_pass_requires_all_gates_and_sha():
    with pytest.raises(ValueError):
        ExecutionEvidence(
            task_id="t1",
            loop_id="hand-sign",
            base_sha=VALID_BASE,
            result=ExecutionResult.PASS,
            produced_sha=None,
            tests_passed=True,
            verified=True,
            safety_gate_passed=True,
            actual_changes=("uhip/schema.py",),
            sheets_write_result="RECORDED",
        )

    with pytest.raises(ValueError):
        ExecutionEvidence(
            task_id="t1",
            loop_id="hand-sign",
            base_sha=VALID_BASE,
            result=ExecutionResult.PASS,
            produced_sha=VALID_BASE,
            tests_passed=True,
            verified=True,
            safety_gate_passed=True,
            actual_changes=("uhip/schema.py",),
            sheets_write_result="RECORDED",
        )


def test_pass_requires_all_gates_and_recorded_sheet():
    evidence = ExecutionEvidence(
        task_id="t1",
        loop_id="hand-sign",
        base_sha=VALID_BASE,
        result=ExecutionResult.PASS,
        produced_sha=VALID_PRODUCED,
        tests_passed=True,
        verified=True,
        safety_gate_passed=True,
        actual_changes=("uhip/schema.py",),
        sheets_write_result="RECORDED",
    )
    assert integration_ready(evidence)


def test_pass_without_sheet_is_not_integration_ready():
    evidence = ExecutionEvidence(
        task_id="t2",
        loop_id="hand-sign",
        base_sha=VALID_BASE,
        result=ExecutionResult.PASS,
        produced_sha=VALID_PRODUCED,
        tests_passed=True,
        verified=True,
        safety_gate_passed=True,
        actual_changes=("uhip/schema.py",),
    )
    assert not integration_ready(evidence)


def test_fail_is_never_integration_ready():
    evidence = ExecutionEvidence(
        task_id="t3",
        loop_id="hand-sign",
        base_sha=VALID_BASE,
        result=ExecutionResult.FAIL,
        produced_sha=VALID_PRODUCED,
        tests_passed=False,
        verified=False,
        safety_gate_passed=False,
        error="pytest failed",
    )
    assert not integration_ready(evidence)
    assert evidence.as_audit_row()["error"] == "pytest failed"


def test_audit_row_has_stable_columns():
    evidence = ExecutionEvidence(
        task_id="t4",
        loop_id="english-core-image",
        base_sha=VALID_BASE,
        result=ExecutionResult.STOPPED,
        produced_sha=None,
        tests_passed=False,
        verified=False,
        safety_gate_passed=False,
        sheets_write_result="not_attempted",
    )
    assert list(evidence.as_audit_row()) == [
        "task_id",
        "loop_id",
        "base_sha",
        "result",
        "produced_sha",
        "tests_passed",
        "verified",
        "safety_gate_passed",
        "actual_changes",
        "error",
        "sheets_write_result",
    ]
