import pytest

from core.loop_execution_contract import (
    ExecutionEvidence,
    ExecutionResult,
    integration_ready,
)


def test_pass_requires_all_gates_and_sha():
    with pytest.raises(ValueError):
        ExecutionEvidence(
            task_id="t1",
            loop_id="hand-sign",
            base_sha="abc",
            result=ExecutionResult.PASS,
            produced_sha=None,
            tests_passed=True,
            verified=True,
            safety_gate_passed=True,
        )

    evidence = ExecutionEvidence(
        task_id="t1",
        loop_id="hand-sign",
        base_sha="abc",
        result=ExecutionResult.PASS,
        produced_sha="def",
        tests_passed=True,
        verified=True,
        safety_gate_passed=True,
        actual_changes=("uhip/schema.py",),
    )
    assert integration_ready(evidence)
    assert evidence.as_audit_row()["actual_changes"] == "uhip/schema.py"


def test_fail_is_never_integration_ready():
    evidence = ExecutionEvidence(
        task_id="t2",
        loop_id="hand-sign",
        base_sha="abc",
        result=ExecutionResult.FAIL,
        produced_sha="def",
        tests_passed=False,
        verified=False,
        safety_gate_passed=False,
        error="pytest failed",
    )
    assert not integration_ready(evidence)
    assert evidence.as_audit_row()["error"] == "pytest failed"


def test_audit_row_has_stable_columns():
    evidence = ExecutionEvidence(
        task_id="t3",
        loop_id="english-core-image",
        base_sha="abc",
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
