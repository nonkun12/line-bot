from agents.english.node import agent as english_agent
from agents.news.node import agent as news_agent
from agents.stocks.node import agent as stocks_agent
from agents.voice.node import agent as voice_agent
from core.agents import AgentRequest
from graph.supervisor import classify_intent


def req(text):
    return AgentRequest(user_id="u", message=text)


def test_four_feature_agents_are_registered_contracts():
    assert english_agent.can_handle(req("英語を勉強したい"))
    assert stocks_agent.can_handle(req("株価を見たい"))
    assert news_agent.can_handle(req("AI NEWSを教えて"))
    assert voice_agent.can_handle(req("AIスピーカーで話して"))


def test_supervisor_routes_four_feature_intents():
    assert classify_intent("英語を勉強したい") == "english_learning"
    assert classify_intent("株価を見たい") == "stocks"
    assert classify_intent("AI NEWSを教えて") == "ai_news"
    assert classify_intent("AIスピーカーで話して") == "voice"
