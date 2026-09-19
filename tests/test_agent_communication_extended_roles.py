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


def test_specialist_to_specialist_route_remains_bounded():
    assert AgentMessageCoordinator.validate_route("market", "music") == ()
    assert AgentMessageCoordinator.validate_route("unknown", "music")
