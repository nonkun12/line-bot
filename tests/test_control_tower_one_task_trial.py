"""One-task Control Tower trial: decision-only checks, no task execution.

These tests validate the selector's authorization boundary. They deliberately do
not invoke the autonomous runtime, mutate queue/state, merge, or deploy.
"""
from __future__ import annotations

import pytest

from core.control_tower_selector import select_next_task

HEAD = "a" * 40


def decide(queue, *, registered=("trial-task",), completed=(), held=(), evidence=HEAD, head=HEAD):
    return select_next_task(
        queue,
        registered,
        completed,
        held,
        evidence_sha=evidence,
        current_head_sha=head,
    )


def test_trial_selects_exactly_one_registered_task_when_evidence_matches_head():
    result = decide(["trial-task"])

    assert result.next_action == "SELECT_REGISTERED_TASK"
    assert result.gate_status == "PASS"
    assert result.task_template_id == "trial-task"
    assert result.evidence_sha == HEAD


@pytest.mark.parametrize(
    "kwargs",
    [
        {"held": ("trial-task",)},
        {"evidence": "b" * 40},
        {"head": "b" * 40},
        {"registered": ()},
        {"queue": ["trial-task", "trial-task"]},
    ],
)
def test_trial_must_hold_on_any_safety_gate_failure(kwargs):
    queue = kwargs.pop("queue", ["trial-task"])
    result = decide(queue, **kwargs)

    assert result.next_action == "HOLD"
    assert result.gate_status == "BLOCKED"
    assert result.task_template_id is None


def test_trial_does_not_run_when_queue_is_empty():
    result = decide([])

    assert result.next_action == "NOT_RUN"
    assert result.gate_status == "NOT_RUN"
    assert result.task_template_id is None


def test_trial_does_not_reselect_completed_task():
    result = decide(["trial-task"], completed=("trial-task",))

    assert result.next_action == "NOT_RUN"
    assert result.gate_status == "NOT_RUN"
    assert result.task_template_id is None


def test_trial_blocks_unregistered_task_even_if_another_task_is_eligible():
    result = decide(
        ["unknown-task", "trial-task"],
        registered=("trial-task",),
    )

    assert result.next_action == "HOLD"
    assert result.gate_status == "BLOCKED"
    assert result.task_template_id is None
