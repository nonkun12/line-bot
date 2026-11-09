import pytest

from core.agent_communication import AgentMessage


def test_agent_message_preserves_one_shot_safety_constraints() -> None:
    constraints = (value for value in ("result-only", "no-permission-grant"))
    message = AgentMessage(
        message_id="m1",
        sender="news",
        recipient="management",
        message_type="task_result",
        content="ok",
        safety_constraints=constraints,
    )
    assert message.safety_constraints == frozenset(
        {"result-only", "no-permission-grant"}
    )


from core.agent_communication import AgentMessageBus, AgentMessageCoordinator


def test_management_can_assign_bounded_task_without_granting_permissions():
    bus = AgentMessageBus()
    manager = bus.endpoint("management")
    english = bus.endpoint("english")

    sent = manager.send(
        "english",
        message_id="assign-1",
        message_type="task_assignment",
        content="Draft and validate a vocabulary candidate",
        correlation_id="cycle-1",
        context={"task_id": "word-1"},
        safety_constraints=("task-only", "no-permission-grant"),
    )

    received = english.receive()
    assert received == (sent,)
    assert received[0].sender == "management"


def test_specialists_can_request_bounded_collaboration():
    bus = AgentMessageBus()
    english = bus.endpoint("english")
    rea = bus.endpoint("general")

    sent = english.send(
        "general",
        message_id="review-request-1",
        message_type="collaboration_request",
        content="Independently review this candidate",
        correlation_id="cycle-1",
        context={"task_id": "word-1"},
        safety_constraints=("task-only", "no-permission-grant"),
    )

    assert rea.receive() == (sent,)


def test_assignment_or_collaboration_cannot_grant_permissions():
    assert AgentMessageCoordinator.validate_route(
        "management",
        "english",
        message_type="task_assignment",
        safety_constraints=("task-only", "grant-tools"),
    )
    assert AgentMessageCoordinator.validate_route(
        "english",
        "general",
        message_type="collaboration_request",
        safety_constraints=("task-only",),
    )


def test_full_mailbox_rejects_new_message_without_dropping_assignment():
    bus = AgentMessageBus(max_messages=1)
    manager = bus.endpoint("management")
    english = bus.endpoint("english")
    news = bus.endpoint("news")

    assignment = manager.send(
        "english", message_id="protected-assignment", message_type="task_assignment",
        content="Execute approved task", context={"task_id": "critical-task"},
        safety_constraints=("task-only", "no-permission-grant"),
    )
    with pytest.raises(ValueError, match="mailbox full"):
        news.send(
            "english", message_id="overflow-collaboration",
            message_type="collaboration_request", content="Please help",
            context={"task_id": "other-task"},
            safety_constraints=("task-only", "no-permission-grant"),
        )

    assert english.peek() == (assignment,)
    assert english.receive() == (assignment,)
