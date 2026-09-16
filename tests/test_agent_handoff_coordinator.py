import pytest

from core.agent_handoff import AgentHandoff, HandoffStatus
from core.agent_handoff_coordinator import AgentHandoffCoordinator


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


def test_submit_accepts_developer_to_debug_without_granting_actions():
    decision = AgentHandoffCoordinator().submit(make_handoff())
    assert decision.accepted is True
    assert decision.handoff is not None
    assert decision.handoff.status is HandoffStatus.ACCEPTED
    assert decision.handoff.allowed_actions == ("read_tests",)
    assert decision.handoff.safety_constraints == ("read_only", "no_deploy")


def test_submit_accepts_debug_to_test():
    decision = AgentHandoffCoordinator().submit(
        make_handoff(source_agent="debug", target_agent="test")
    )
    assert decision.accepted is True


@pytest.mark.parametrize(
    ("source", "target"),
    [("manager", "debug"), ("developer", "manager"), ("test", "manager")],
)
def test_submit_rejects_unapproved_routes(source, target):
    decision = AgentHandoffCoordinator().submit(
        make_handoff(source_agent=source, target_agent=target)
    )
    assert decision.accepted is False
    assert decision.handoff is None
    assert any("route" in error or "approved" in error for error in decision.errors)


def test_submit_fails_closed_for_invalid_packet():
    decision = AgentHandoffCoordinator().submit(
        make_handoff(task="", safety_constraints=())
    )
    assert decision.accepted is False
    assert decision.handoff is None
    assert decision.errors


def test_complete_requires_accepted_handoff():
    coordinator = AgentHandoffCoordinator()
    proposed = make_handoff()
    decision = coordinator.complete(proposed)
    assert decision.accepted is False
    assert decision.handoff is None

    accepted = coordinator.submit(proposed).handoff
    assert accepted is not None
    completed = coordinator.complete(accepted)
    assert completed.accepted is True
    assert completed.handoff is not None
    assert completed.handoff.status is HandoffStatus.COMPLETED
