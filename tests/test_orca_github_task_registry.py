"""Safety tests for Orca's finite typed task registry.

These tests prove that catalogued tasks remain non-executable until a reviewed
handler exists, and that free-form queue payloads cannot select code or paths.
"""
import pytest

from scripts.orca_github_task_registry import (
    TaskContractRejected,
    validate_typed_task,
)


@pytest.mark.parametrize(
    ("task_id", "target_path"),
    [
        ("ai-speaker-empty-transcript-no-brain-call", "tests/test_ai_speaker.py"),
        ("recovery-ai-state-isolation", "tests/test_recovery_ai.py"),
        ("router-regression-general-request-metadata", "tests/test_management_router.py"),
        (
            "recovery-ai-loop-adapter-durable-state-readback",
            "tests/test_recovery_ai_loop_adapter.py",
        ),
    ],
)
def test_allowlisted_tasks_are_validated_but_never_executable(task_id, target_path):
    result = validate_typed_task(
        task_id=task_id,
        payload={
            "task_type": "add_regression_test",
            "target_path": target_path,
            "contract_version": 1,
        },
    )

    assert result == {
        "task_id": task_id,
        "task_type": "add_regression_test",
        "target_path": target_path,
        "contract_version": 1,
        "execution_supported": False,
        "status": "BLOCKED_HANDLER_NOT_IMPLEMENTED",
    }


@pytest.mark.parametrize(
    ("task_id", "payload"),
    [
        ("unknown-task", {
            "task_type": "add_regression_test",
            "target_path": "tests/test_anything.py",
            "contract_version": 1,
        }),
        ("ai-speaker-empty-transcript-no-brain-call", {
            "task_type": "shell",
            "target_path": "tests/test_ai_speaker.py",
            "contract_version": 1,
        }),
        ("ai-speaker-empty-transcript-no-brain-call", {
            "task_type": "add_regression_test",
            "target_path": "../../arbitrary.py",
            "contract_version": 1,
        }),
        ("ai-speaker-empty-transcript-no-brain-call", {
            "task_type": "add_regression_test",
            "target_path": "tests/test_ai_speaker.py",
            "contract_version": True,
        }),
        ("ai-speaker-empty-transcript-no-brain-call", {
            "task_type": "add_regression_test",
            "target_path": "tests/test_ai_speaker.py",
            "contract_version": 1,
            "command": "arbitrary command",
        }),
    ],
)
def test_untyped_or_mismatched_payloads_are_rejected(task_id, payload):
    with pytest.raises(TaskContractRejected):
        validate_typed_task(task_id=task_id, payload=payload)


@pytest.mark.parametrize("payload", [None, [], "not-an-object", 1])
def test_non_object_payloads_are_rejected(payload):
    with pytest.raises(TaskContractRejected):
        validate_typed_task(
            task_id="ai-speaker-empty-transcript-no-brain-call",
            payload=payload,
        )
