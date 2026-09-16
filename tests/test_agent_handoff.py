import pytest

from core.agent_handoff import AgentHandoff, HandoffStatus


def make_handoff(**overrides):
    values = {
        "handoff_id": "h-1",
        "source_agent": "developer",
        "target_agent": "debug",
        "task": "inspect the failing test",
        "allowed_actions": ("read_tests",),
        "safety_constraints": ("read_only", "no_deploy"),
    }
    values.update(overrides)
    return AgentHandoff(**values)


def test_valid_handoff_has_no_validation_errors():
    assert make_handoff().validate() == ()


def test_validation_fails_closed_for_missing_required_fields():
    errors = make_handoff(handoff_id="", task="", safety_constraints=()).validate()
    assert "handoff_id is required" in errors
    assert "task is required" in errors
    assert "at least one safety constraint is required" in errors


def test_self_handoff_is_rejected():
    errors = make_handoff(target_agent="developer").validate()
    assert "source_agent and target_agent must differ" in errors


def test_handoff_lifecycle_is_strict_and_immutable():
    proposed = make_handoff()
    accepted = proposed.transition(HandoffStatus.ACCEPTED)
    completed = accepted.transition(HandoffStatus.COMPLETED)

    assert proposed.status is HandoffStatus.PROPOSED
    assert accepted.status is HandoffStatus.ACCEPTED
    assert completed.status is HandoffStatus.COMPLETED
    with pytest.raises(ValueError):
        completed.transition(HandoffStatus.REJECTED)


def test_rejected_handoff_cannot_be_reactivated():
    rejected = make_handoff().transition(HandoffStatus.REJECTED)
    with pytest.raises(ValueError):
        rejected.transition(HandoffStatus.ACCEPTED)


def test_transition_does_not_grant_new_actions_or_constraints():
    accepted = make_handoff().transition(HandoffStatus.ACCEPTED)
    assert accepted.allowed_actions == ("read_tests",)
    assert accepted.safety_constraints == ("read_only", "no_deploy")
