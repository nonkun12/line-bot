"""Fail-closed regression tests for the real Control Tower loop adapter.

These tests exercise authorization only; they never invoke a task executor,
write runtime state, merge, or deploy.
"""
from __future__ import annotations

import copy

import pytest

from scripts.control_tower_loop_adapter import authorize_registered_task

HEAD = "a" * 40
TASK = {
    "id": "trial-task",
    "instruction": "mocked one-task trial only",
    "allowed_paths": ["tests/test_control_tower_one_task_trial.py"],
}


def test_adapter_authorizes_exact_registered_task_at_valid_head():
    assert authorize_registered_task(copy.deepcopy(TASK), [copy.deepcopy(TASK)], HEAD) == (
        True,
        "registered_task_and_current_head_verified",
    )


@pytest.mark.parametrize(
    ("task", "catalog", "head", "expected_reason"),
    [
        (TASK, [TASK], "invalid-sha", "invalid_current_head_sha"),
        ({**TASK, "instruction": "changed instruction"}, [TASK], HEAD, "task_definition_mismatch"),
        ({**TASK, "allowed_paths": ["core/control_tower_decision.py"]}, [TASK], HEAD, "task_definition_mismatch"),
        (TASK, [], HEAD, "task_not_uniquely_registered"),
        (TASK, [TASK, TASK], HEAD, "task_not_uniquely_registered"),
        ({**TASK, "id": "unknown-task"}, [TASK], HEAD, "task_not_uniquely_registered"),
        ({**TASK, "instruction": "  "}, [{**TASK, "instruction": "  "}], HEAD, "invalid_task_instruction"),
        ({**TASK, "allowed_paths": []}, [{**TASK, "allowed_paths": []}], HEAD, "invalid_allowed_paths"),
    ],
)
def test_adapter_rejects_invalid_evidence_or_task_definition(
    task, catalog, head, expected_reason
):
    allowed, reason = authorize_registered_task(task, catalog, head)
    assert allowed is False
    assert reason == expected_reason
