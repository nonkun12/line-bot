from agents.english_agent import EnglishLearningAgent, build_english_responder
from core.agents import AgentRequest


def test_english_agent_detects_learning_requests():
    agent = EnglishLearningAgent()
    assert agent.can_handle(AgentRequest(user_id="U1", message="英語を練習したい"))
    assert agent.can_handle(AgentRequest(user_id="U1", message="English conversation"))
    assert not agent.can_handle(AgentRequest(user_id="U1", message="東京の天気"))


def test_injected_responder_is_channel_neutral():
    handler = build_english_responder(lambda lesson: f"Correction for: {lesson.prompt}")
    response = handler(AgentRequest(user_id="U1", message="I has a pen", channel="line"))
    assert response.text == "Correction for: I has a pen"
    assert response.metadata["feature"] == "english"
