from agents.english.node import EnglishLearningAgent
from agents.news.node import AINewsAgent
from agents.stocks.node import StocksAgent
from agents.voice.node import VoiceAgent
from core.agents import AgentRequest
from graph.supervisor import classify_intent


def _request(message: str) -> AgentRequest:
    return AgentRequest(user_id="test-user", message=message, channel="test")


def test_supervisor_routes_four_specialist_intents():
    cases = (
        ("英語 クイズ", "english_learning"),
        ("AAPLの株価", "stocks"),
        ("AI NEWSを教えて", "ai_news"),
        ("speakerで話して", "voice"),
    )
    for message, expected in cases:
        assert classify_intent(message, user_id="test-user") == expected


def test_english_agent_quiz_is_actionable():
    response = EnglishLearningAgent().handle(_request("英語 クイズ"))
    assert "A. improve" in response.text
    assert response.metadata["feature"] == "english_learning"


def test_stocks_agent_uses_quote_data_without_network(monkeypatch):
    agent = StocksAgent()
    monkeypatch.setattr(
        agent,
        "_fetch_quote",
        lambda ticker: {
            "ticker": "AAPL",
            "price": 200.0,
            "previous_close": 195.0,
            "change": 5.0,
            "change_pct": 2.5641,
            "currency": "USD",
            "market_time": None,
            "market_time_jst": None,
            "market_state": "REGULAR",
        },
    )
    response = agent.handle(_request("AAPLの株価"))
    assert "現在値: 200.00 USD" in response.text
    assert "前日比: +5.00 USD" in response.text
    assert response.metadata["status"] == "online"


def test_news_agent_formats_retrieved_items_without_network(monkeypatch):
    agent = AINewsAgent()
    monkeypatch.setattr(
        agent,
        "_fetch",
        lambda query: [
            {
                "title": "New AI model released",
                "link": "https://example.com/ai",
                "published": "09/15 04:00",
                "source": "Example News",
            }
        ],
    )
    response = agent.handle(_request("AI NEWS"))
    assert "New AI model released" in response.text
    assert "Example News" in response.text
    assert response.metadata["count"] == 1


def test_voice_agent_has_safe_text_fallback():
    response = VoiceAgent().handle(_request("speakerで話して"))
    assert response.metadata["feature"] == "voice"
    assert response.metadata["speech_available"] is False
    assert response.metadata["speech_provider"] == "none"
