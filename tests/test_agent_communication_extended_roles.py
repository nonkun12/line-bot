import pytest

from core.agent_communication import AgentMessage, AgentMessageCoordinator, AgentMessageBus


def test_all_management_plannable_specialists_are_valid_message_routes():
    for role in ("general", "voice", "english", "news", "stocks", "market", "jobs", "music", "video"):
        assert AgentMessageCoordinator.validate_route(role, "management") == ()
        assert AgentMessageCoordinator.validate_route("management", role) == ()


def test_extended_specialist_result_can_reach_management():
    bus = AgentMessageBus(max_messages=2)
    message = AgentMessage(
        message_id="video-1:result",
        sender="video",
        recipient="management",
        message_type="task_result",
        content="video result",
        correlation_id="req-1",
        safety_constraints=("result-only", "no-permission-grant"),
    )
    assert bus.send(message) == message
    assert bus.receive("management") == (message,)


def test_specialist_to_specialist_result_is_bounded_and_safe():
    bus = AgentMessageBus(max_messages=2)
    message = AgentMessage(
        message_id="market-1:result",
        sender="market",
        recipient="music",
        message_type="task_result",
        content="bounded result",
        safety_constraints=("result-only", "no-permission-grant"),
    )
    assert bus.send(message) == message
    assert bus.receive("music") == (message,)


def test_specialist_to_specialist_instruction_is_rejected():
    bus = AgentMessageBus()
    with pytest.raises(ValueError, match="must be task_result"):
        bus.send(
            AgentMessage(
                message_id="market-1:instruction",
                sender="market",
                recipient="music",
                message_type="task_assignment",
                content="execute this instruction",
                safety_constraints=("result-only", "no-permission-grant"),
            )
        )


def test_specialist_to_specialist_without_result_safety_is_rejected():
    bus = AgentMessageBus()
    with pytest.raises(ValueError, match="require result-only"):
        bus.send(
            AgentMessage(
                message_id="market-1:result",
                sender="market",
                recipient="music",
                message_type="task_result",
                content="unsafe result envelope",
                safety_constraints=("no-permission-grant",),
            )
        )


def test_specialist_to_specialist_route_remains_registered():
    assert AgentMessageCoordinator.validate_route("market", "music") == ()
    assert AgentMessageCoordinator.validate_route("unknown", "music")
