from __future__ import annotations

import pytest

from core.control_tower_decision import ControlTowerDecisionRecord


VALID_SHA = "a" * 40


def test_registered_task_selection_requires_pass_and_evidence() -> None:
    decision = ControlTowerDecisionRecord(
        reason_code="recurring_failure",
        confidence=0.8,
        priority=70,
        next_action="SELECT_REGISTERED_TASK",
        gate_status="PASS",
        evidence_sha=VALID_SHA,
        task_template_id="router-regression",
    )

    assert decision.execution_eligible({"router-regression"})
    assert not decision.execution_eligible({"other-registered-task"})
    assert not decision.execution_eligible(set())


@pytest.mark.parametrize(
    "overrides",
    [
        {"gate_status": "BLOCKED"},
        {"evidence_sha": None},
        {"task_template_id": None},
    ],
)
def test_task_selection_fails_closed_when_required_gate_or_evidence_missing(
    overrides: dict[str, object],
) -> None:
    fields: dict[str, object] = {
        "reason_code": "evidence_sufficient",
        "confidence": 0.9,
        "priority": 50,
        "next_action": "SELECT_REGISTERED_TASK",
        "gate_status": "PASS",
        "evidence_sha": VALID_SHA,
        "task_template_id": "safe-template",
    }
    fields.update(overrides)

    with pytest.raises(ValueError):
        ControlTowerDecisionRecord(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_confidence_must_be_finite_and_bounded(confidence: object) -> None:
    with pytest.raises(ValueError):
        ControlTowerDecisionRecord(
            reason_code="evidence_sufficient",
            confidence=confidence,  # type: ignore[arg-type]
            priority=10,
            next_action="OBSERVE_ONLY",
            gate_status="PASS",
        )


def test_unknown_reason_or_action_is_rejected() -> None:
    with pytest.raises(ValueError):
        ControlTowerDecisionRecord(
            reason_code="run_arbitrary_model_instruction",
            confidence=0.5,
            priority=10,
            next_action="OBSERVE_ONLY",
            gate_status="PASS",
        )
    with pytest.raises(ValueError):
        ControlTowerDecisionRecord(
            reason_code="evidence_sufficient",
            confidence=0.5,
            priority=10,
            next_action="EXECUTE_FREE_FORM_INSTRUCTION",
            gate_status="PASS",
        )


def test_non_selection_actions_cannot_smuggle_a_task_template() -> None:
    with pytest.raises(ValueError):
        ControlTowerDecisionRecord(
            reason_code="reviewer_unavailable",
            confidence=0.0,
            priority=0,
            next_action="HOLD",
            gate_status="BLOCKED",
            task_template_id="unreviewed-template",
        )


def test_queue_empty_can_only_be_recorded_as_not_run_without_task() -> None:
    decision = ControlTowerDecisionRecord(
        reason_code="queue_empty",
        confidence=1.0,
        priority=0,
        next_action="NOT_RUN",
        gate_status="NOT_RUN",
        evidence_sha=VALID_SHA,
    )

    assert not decision.execution_eligible({"any-registered-task"})
