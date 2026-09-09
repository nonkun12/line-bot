import pytest

from core.gateway import AIGateway, AIRequest, AIResponse


def test_gateway_accepts_text_handler_without_channel_dependency():
    gateway = AIGateway(lambda request: f"echo:{request.message}")

    response = gateway.handle(AIRequest(user_id="u1", message="hello", channel="line"))

    assert response == AIResponse(text="echo:hello")


def test_gateway_preserves_structured_response():
    gateway = AIGateway(lambda request: AIResponse("ok", {"agent": "normal"}))

    response = gateway.handle(AIRequest(user_id="u1", message="hello", channel="web"))

    assert response.text == "ok"
    assert response.metadata["agent"] == "normal"


@pytest.mark.parametrize("request", [
    AIRequest(user_id="", message="hello"),
    AIRequest(user_id="u1", message=""),
])
def test_gateway_rejects_missing_required_fields(request):
    with pytest.raises(ValueError):
        AIGateway(lambda _: "ok").handle(request)


def test_gateway_rejects_invalid_handler_result():
    with pytest.raises(TypeError):
        AIGateway(lambda _: 123).handle(AIRequest(user_id="u1", message="hello"))
