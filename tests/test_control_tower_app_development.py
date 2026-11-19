from core.agents import AgentRequest, AgentRegistry
from core.channel import handle_channel_request
from core.gateway import AIGateway, AIResponse
from core.langgraph_adapter import agent_request_from_state
from graph.core_registry import build_core_agent_registry
from graph.supervisor import classify_intent, supervisor_node
from line_development import extract_development_instruction
from agents.app_development.node import app_development_agent_node


def test_app_development_is_classified_by_supervisor():
    assert classify_intent("アプリ開発: テストアプリを作って") == "app_development"
    state = supervisor_node({"user_id": "u1", "raw_message": "アプリ開発: テストアプリを作って"})
    assert state["next_agent"] == "app_development"


def test_app_development_is_registered_with_high_priority():
    registry = build_core_agent_registry()
    agent = registry.get("app_development")
    assert agent.priority == 100
    request = AgentRequest(
        user_id="u1",
        message="アプリ開発: テストアプリを作って",
        channel="line",
        metadata={"next_agent": "app_development"},
    )
    assert registry.resolve(request).name == "app_development"


def test_channel_adapter_does_not_route_app_development_itself():
    seen = {}

    def handler(request):
        seen["channel"] = request.channel
        seen["message"] = request.message
        return AIResponse(text="handled by gateway")

    response = handle_channel_request(
        AIGateway(handler),
        "u1",
        "アプリ開発: テストアプリを作って",
        "line",
    )
    assert response.text == "handled by gateway"
    assert seen == {
        "channel": "line",
        "message": "アプリ開発: テストアプリを作って",
    }


def test_agent_request_preserves_channel_and_metadata():
    state = {
        "user_id": "u1",
        "raw_message": "天気を教えて",
        "channel": "voice",
        "metadata": {"marker": "keep"},
    }
    request = agent_request_from_state(state)
    assert request.channel == "voice"
    assert request.metadata["marker"] == "keep"


def test_normal_development_dispatcher_no_longer_owns_app_development():
    assert extract_development_instruction("アプリ開発: 天気アプリを作って") is None
    assert extract_development_instruction("開発: テストを追加して") == "テストを追加して"


def test_app_development_agent_denies_unconfigured_user_without_dispatch(monkeypatch):
    monkeypatch.delenv("DEV_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "")
    state = {
        "user_id": "unauthorized-user",
        "raw_message": "アプリ開発: テストアプリを作って",
        "channel": "line",
        "agent_results": {},
    }
    result = app_development_agent_node(state)
    assert "権限がありません" in result["agent_results"]["app_development"]["text"]
