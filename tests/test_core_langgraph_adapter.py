import pytest

from core.agents import AgentResponse
from core.gateway import AIRequest
from core.langgraph_adapter import (
    agent_request_from_state,
    ai_request_from_state,
    response_text,
)


def test_ai_request_from_state_maps_legacy_fields():
    state = {
        "user_id": "u1",
        "raw_message": "hello",
        "request_id": "r1",
        "intent": "normal",
        "next_agent": "normal_agent",
    }

    request = ai_request_from_state(state, channel="web")

    assert request == AIRequest(
        user_id="u1",
        message="hello",
        channel="web",
        metadata={
            "request_id": "r1",
            "intent": "normal",
            "next_agent": "normal_agent",
        },
    )


def test_agent_request_from_state_maps_legacy_fields():
    request = agent_request_from_state(
        {"user_id": "u1", "raw_message": "hello", "request_id": "r1"}
    )

    assert request.user_id == "u1"
    assert request.message == "hello"
    assert request.metadata["request_id"] == "r1"


def test_response_text_normalizes_core_response():
    assert response_text(AgentResponse(text="hello")) == "hello"
    assert response_text("hello") == "hello"


def test_response_text_rejects_invalid_value():
    with pytest.raises(TypeError, match="AgentResponse or str"):
        response_text(object())
