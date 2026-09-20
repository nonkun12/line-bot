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
