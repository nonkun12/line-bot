from core.channel import handle_channel_request
from core.gateway import AIGateway, AIResponse, AIRequest


def test_handle_channel_request_builds_shared_gateway_request():
    captured = {}

    def handler(request: AIRequest):
        captured["request"] = request
        return AIResponse(text="ok")

    response = handle_channel_request(
        AIGateway(handler),
        "u1",
        "hello",
        "iphone",
        metadata={"route": "voice"},
    )

    assert response.text == "ok"
    request = captured["request"]
    assert request.user_id == "u1"
    assert request.message == "hello"
    assert request.channel == "iphone"
    assert request.metadata == {"route": "voice"}


def test_handle_channel_request_does_not_require_channel_specific_logic():
    calls = []

    def handler(request: AIRequest):
        calls.append(request.channel)
        return "reply"

    gateway = AIGateway(handler)
    assert handle_channel_request(gateway, "u1", "line", "line").text == "reply"
    assert handle_channel_request(gateway, "u1", "voice", "voice").text == "reply"
    assert handle_channel_request(gateway, "u1", "web", "web").text == "reply"
    assert calls == ["line", "voice", "web"]
