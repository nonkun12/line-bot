import pytest

from core.gateway import AIGateway, AIRequest, AIResponse


def test_gateway_adapts_string_response():
    gateway = AIGateway(lambda request: "hello")

    assert gateway.handle(AIRequest("u1", "hi", channel="line")) == AIResponse(text="hello")


def test_gateway_keeps_ai_response():
    expected = AIResponse(text="hello", metadata={"agent": "normal"})
    gateway = AIGateway(lambda request: expected)

    assert gateway.handle(AIRequest("u1", "hi", channel="web")) == expected


def test_gateway_rejects_invalid_request_fields():
    gateway = AIGateway(lambda request: "hello")

    with pytest.raises(ValueError, match="user_id is required"):
        gateway.handle(AIRequest(123, "hi", channel="line"))
    with pytest.raises(ValueError, match="user_id is required"):
        gateway.handle(AIRequest("   ", "hi", channel="line"))
    with pytest.raises(ValueError, match="message is required"):
        gateway.handle(AIRequest("u1", "", channel="line"))
    with pytest.raises(ValueError, match="message is required"):
        gateway.handle(AIRequest("u1", "   ", channel="line"))
    with pytest.raises(ValueError, match="channel is required"):
        gateway.handle(AIRequest("u1", "hi", channel=""))
    with pytest.raises(ValueError, match="channel is required"):
        gateway.handle(AIRequest("u1", "hi", channel="   "))


def test_gateway_rejects_invalid_handler_result():
    gateway = AIGateway(lambda request: object())

    with pytest.raises(TypeError, match="AIResponse or str"):
        gateway.handle(AIRequest("u1", "hi", channel="line"))


def test_gateway_rejects_non_callable_handler():
    with pytest.raises(TypeError, match="handler must be callable"):
        AIGateway(object())
