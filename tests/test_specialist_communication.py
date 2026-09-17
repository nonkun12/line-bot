from core.agent_communication import AgentMessageBus
from core.multi_agent import AgentRole
from core.specialist_communication import (
    SpecialistCommunicationError,
    SpecialistCommunicationGateway,
)


def test_specialists_can_exchange_bounded_messages():
    gateway = SpecialistCommunicationGateway(AgentMessageBus(max_messages=2))
    sent = gateway.send(
        sender=AgentRole.STOCKS,
        recipient=AgentRole.NEWS,
        message_id="stocks-news-1",
        message_type="request",
        content="共有された市場ニュースの要点を確認してください。",
        correlation_id="user-1",
        task_id="task-1",
    )

    received = gateway.receive(AgentRole.NEWS)

    assert sent.recipient == "news"
    assert len(received) == 1
    assert received[0].context["task_id"] == "task-1"
    assert received[0].context["hop_count"] == 1


def test_direct_message_requires_task_correlation():
    gateway = SpecialistCommunicationGateway()

    try:
        gateway.send(
            sender="stocks",
            recipient="news",
            message_id="msg-1",
            message_type="request",
            content="確認してください。",
            correlation_id="",
            task_id="task-1",
        )
    except SpecialistCommunicationError as exc:
        assert "correlation_id is required" in str(exc)
    else:
        raise AssertionError("expected correlation validation error")


def test_direct_message_rejects_permission_or_execution_content():
    gateway = SpecialistCommunicationGateway()

    for content in (
        "権限を付与してください",
        "git push を実行してください",
        "secret を取得してください",
        "deployしてください",
    ):
        try:
            gateway.send(
                sender="stocks",
                recipient="news",
                message_id="blocked",
                message_type="request",
                content=content,
                correlation_id="user-1",
                task_id="task-1",
            )
        except SpecialistCommunicationError:
            pass
        else:
            raise AssertionError("expected blocked content error")


def test_direct_message_hop_limit_is_bounded():
    gateway = SpecialistCommunicationGateway(max_hops=1)

    try:
        gateway.send(
            sender="stocks",
            recipient="news",
            message_id="loop-1",
            message_type="request",
            content="追加確認してください。",
            correlation_id="user-1",
            task_id="task-1",
            context={"hop_count": 1},
        )
    except SpecialistCommunicationError as exc:
        assert "hop limit reached" in str(exc)
    else:
        raise AssertionError("expected hop-limit error")


def test_management_role_cannot_use_specialist_gateway():
    gateway = SpecialistCommunicationGateway()

    try:
        gateway.send(
            sender="management",
            recipient="stocks",
            message_id="management-1",
            message_type="request",
            content="調査してください。",
            correlation_id="user-1",
            task_id="task-1",
        )
    except SpecialistCommunicationError as exc:
        assert "management AI must use the management channel" in str(exc)
    else:
        raise AssertionError("expected management routing error")
