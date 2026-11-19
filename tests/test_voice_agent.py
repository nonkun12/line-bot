from agents.voice.node import VoiceAgent
from core.agents import AgentRequest


def test_voice_agent_exposes_text_only_capability_by_default():
    response = VoiceAgent().handle(
        AgentRequest(user_id="U1", message="しゃべって", channel="voice")
    )

    assert response.metadata["feature"] == "voice"
    assert response.metadata["speech_provider"] == "none"
    assert response.metadata["speech_available"] is False
    assert response.text
