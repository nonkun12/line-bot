import copy
import hashlib
import json

import pytest

from scripts.validate_task_bound_approval import (
    ApprovalError,
    allowed_paths_digest,
    build_one_time_approval_catalog,
)


TASK_ID = "test-task-one"
INSTRUCTION = "Add one isolated regression test."
PATHS = ["tests/test_one.py"]
BASE_SHA = "a" * 40


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _inputs():
    task = {"id": TASK_ID, "instruction": INSTRUCTION, "allowed_paths": PATHS}
    queue = {"tasks": [copy.deepcopy(task)]}
    catalog = {"version": 1, "tasks": [copy.deepcopy(task), {
        "id": "other-task", "instruction": "Other task.", "allowed_paths": ["tests/test_two.py"],
        "execution_approved": True,
    }]}
    state = {"completed": [], "recovery_ai": {"tasks": {}}}
    kwargs = {
        "queue": queue,
        "catalog": catalog,
        "state": state,
        "approval": "APPROVE_EXECUTION",
        "task_id": TASK_ID,
        "allowed_paths_sha256": allowed_paths_digest(PATHS),
        "instruction_sha256": _digest(INSTRUCTION),
        "approval_base_sha": BASE_SHA,
        "current_base_sha": BASE_SHA,
    }
    return kwargs


def test_one_time_approval_enables_only_the_exact_task():
    kwargs = _inputs()
    original = copy.deepcopy(kwargs["catalog"])
    result = build_one_time_approval_catalog(**kwargs)
    approved = {item["id"]: item["execution_approved"] for item in result["tasks"]}
    assert approved == {TASK_ID: True, "other-task": False}
    assert kwargs["catalog"] == original


@pytest.mark.parametrize("field,value,reason", [
    ("approval", "DENY", "explicit_execution_approval_missing"),
    ("task_id", "missing-task", "approval_task_not_queued_and_registered"),
    ("instruction_sha256", "0" * 64, "approval_instruction_sha256_mismatch"),
    ("allowed_paths_sha256", "0" * 64, "approval_allowed_paths_sha256_mismatch"),
    ("approval_base_sha", "b" * 40, "approval_base_sha_mismatch"),
])
def test_mismatched_approval_inputs_fail_closed(field, value, reason):
    kwargs = _inputs()
    kwargs[field] = value
    with pytest.raises(ApprovalError, match=reason):
        build_one_time_approval_catalog(**kwargs)


@pytest.mark.parametrize("record,reason", [
    ({"held": True}, "approval_task_held"),
    ({"resume_requires_review": True}, "approval_task_requires_review"),
])
def test_held_or_review_pending_task_cannot_be_approved(record, reason):
    kwargs = _inputs()
    kwargs["state"]["recovery_ai"]["tasks"][TASK_ID] = record
    with pytest.raises(ApprovalError, match=reason):
        build_one_time_approval_catalog(**kwargs)


def test_completed_task_cannot_be_approved():
    kwargs = _inputs()
    kwargs["state"]["completed"] = [TASK_ID]
    with pytest.raises(ApprovalError, match="approval_task_already_completed"):
        build_one_time_approval_catalog(**kwargs)


def test_queue_and_catalog_definition_must_match():
    kwargs = _inputs()
    kwargs["queue"]["tasks"][0]["instruction"] = "Changed instruction."
    with pytest.raises(ApprovalError, match="approval_task_definition_mismatch"):
        build_one_time_approval_catalog(**kwargs)


def test_ambiguous_recovery_flags_fail_closed():
    kwargs = _inputs()
    kwargs["state"]["recovery_ai"]["tasks"][TASK_ID] = {"held": "false"}
    with pytest.raises(ApprovalError, match="approval_recovery_flag_invalid"):
        build_one_time_approval_catalog(**kwargs)
