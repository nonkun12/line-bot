from __future__ import annotations

import pytest

from core.control_tower_selector import select_next_task

SHA = "a" * 40


def test_selects_first_registered_eligible_task():
    decision = select_next_task(
        ["unregistered", "task-b", "task-c"],
        ["task-b", "task-c"],
        set(),
        set(),
        evidence_sha=SHA,
        current_head_sha=SHA,
    )
    assert decision.next_action == "SELECT_REGISTERED_TASK"
    assert decision.task_template_id == "task-b"
    assert decision.execution_eligible({"task-b", "task-c"}, SHA)


def test_queue_empty_is_not_run_not_pass():
    decision = select_next_task([], ["task-b"], set(), set(), evidence_sha=SHA, current_head_sha=SHA)
    assert decision.next_action == "NOT_RUN"
    assert decision.gate_status == "NOT_RUN"
    assert decision.reason_code == "queue_empty"


@pytest.mark.parametrize(
    ("queued", "registered", "completed", "held", "evidence", "head", "reason"),
    [
        (["unknown"], ["task-b"], set(), set(), SHA, SHA, "unregistered_task"),
        (["task-b"], ["task-b"], {"task-b"}, set(), SHA, SHA, "duplicate_task"),
        (["task-b", "task-b"], ["task-b"], set(), set(), SHA, SHA, "duplicate_task"),
        (["task-b"], ["task-b"], set(), {"task-b"}, SHA, SHA, "task_held"),
        (["task-b"], ["task-b"], set(), set(), "b" * 40, SHA, "policy_blocked"),
        (["task-b"], ["task-b"], set(), set(), "bad-sha", SHA, "invalid_state"),
    ],
)
def test_invalid_or_ineligible_selection_fails_closed(queued, registered, completed, held, evidence, head, reason):
    decision = select_next_task(
        queued,
        registered,
        completed,
        held,
        evidence_sha=evidence,
        current_head_sha=head,
    )
    assert decision.reason_code == reason
    assert decision.next_action == "HOLD"
    assert decision.gate_status == "BLOCKED"
    assert decision.task_template_id is None


def test_malformed_registry_and_state_fail_closed():
    decision = select_next_task(
        ["task-b"],
        "task-b",
        set(),
        set(),
        evidence_sha=SHA,
        current_head_sha=SHA,
    )
    assert decision.reason_code == "invalid_state"
    assert decision.next_action == "HOLD"
