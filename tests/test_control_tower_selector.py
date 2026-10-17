from __future__ import annotations

import pytest

from core.control_tower_selector import select_next_task

SHA = "a" * 40


def choose(queue, registered=("task-a", "task-b"), completed=(), held=(), **kwargs):
    return select_next_task(
        queue,
        registered,
        completed,
        held,
        evidence_sha=kwargs.get("evidence_sha", SHA),
        current_head_sha=kwargs.get("current_head_sha", SHA),
    )


def test_selects_first_registered_noncompleted_nonheld_task_in_queue_order():
    decision = choose(
        ["task-held", "task-done", "task-b", "task-a"],
        registered=("task-a", "task-b"),
        completed=("task-done",),
        held=("task-held",),
    )

    assert decision.next_action == "SELECT_REGISTERED_TASK"
    assert decision.gate_status == "PASS"
    assert decision.task_template_id == "task-b"
    assert decision.evidence_sha == SHA


def test_empty_queue_is_not_run_and_does_not_select_a_task():
    decision = choose([])

    assert decision.reason_code == "queue_empty"
    assert decision.next_action == "NOT_RUN"
    assert decision.gate_status == "NOT_RUN"
    assert decision.task_template_id is None


def test_all_held_queue_is_blocked_without_unholding_any_task():
    decision = choose(["task-a"], held=("task-a",))

    assert decision.reason_code == "task_held"
    assert decision.next_action == "HOLD"
    assert decision.gate_status == "BLOCKED"
    assert decision.task_template_id is None


def test_duplicate_queue_ids_fail_closed():
    decision = choose(["task-a", "task-a"])

    assert decision.reason_code == "duplicate_task"
    assert decision.next_action == "HOLD"
    assert decision.gate_status == "BLOCKED"


def test_unregistered_queue_task_fails_closed():
    decision = choose(["task-unregistered", "task-a"])

    assert decision.reason_code == "policy_blocked"
    assert decision.next_action == "HOLD"
    assert decision.task_template_id is None


def test_evidence_must_match_current_head_exactly():
    decision = choose(["task-a"], current_head_sha="b" * 40)

    assert decision.reason_code == "policy_blocked"
    assert decision.next_action == "HOLD"
    assert decision.task_template_id is None


@pytest.mark.parametrize(
    "queue,registered,completed,held",
    [
        ([""], ("task-a",), (), ()),
        (["task-a"], "task-a", (), ()),
        (["task-a"], ("task-a",), None, ()),
        (["task-a"], ("task-a",), (), "task-a"),
    ],
)
def test_malformed_selection_inputs_fail_closed(queue, registered, completed, held):
    decision = choose(queue, registered=registered, completed=completed, held=held)

    assert decision.reason_code == "invalid_state"
    assert decision.next_action == "HOLD"
    assert decision.gate_status == "BLOCKED"


def test_completed_only_queue_does_not_reselect_completed_task():
    decision = choose(["task-a"], completed=("task-a",))

    assert decision.reason_code == "no_eligible_task"
    assert decision.next_action == "NOT_RUN"
    assert decision.task_template_id is None


@pytest.mark.parametrize("bad_sha", [None, 123, ""])
def test_malformed_sha_types_fail_closed(bad_sha):
    decision = choose(["task-a"], evidence_sha=bad_sha)

    assert decision.reason_code == "invalid_state"
    assert decision.next_action == "HOLD"
    assert decision.task_template_id is None
