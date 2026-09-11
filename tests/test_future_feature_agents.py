from agents.english.intents import classify_english_mode, is_english_learning_intent
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


def test_english_modes_are_deterministic():
    assert classify_english_mode("単語を勉強") == "vocabulary"
    assert classify_english_mode("grammarを教えて") == "grammar"
    assert classify_english_mode("英会話したい") == "conversation"
    assert classify_english_mode("クイズ") == "quiz"
    assert classify_english_mode("復習したい") == "review"
    assert classify_english_mode("英語を始めたい") == "lesson"


def test_english_agent_returns_usable_mvp_responses():
    for message, marker in (
        ("英語を勉強したい", "英語学習を始めましょう"),
        ("単語", "今日の英単語"),
        ("クイズ", "英単語クイズ"),
        ("文法", "英文法ミニレッスン"),
        ("英会話", "英会話練習を始めます"),
        ("復習", "英語復習モードです"),
    ):
        response = english_agent.handle(req(message))
        assert marker in response.text
        assert response.metadata["status"] == "online"
        assert response.metadata["mode"] == classify_english_mode(message)


def test_english_intent_helper_accepts_japanese_and_english_terms():
    assert is_english_learning_intent("English practice")
    assert is_english_learning_intent("英単語")
    assert not is_english_learning_intent("天気を教えて")


def test_ai_news_agent_formats_retrieved_headlines(monkeypatch):
    monkeypatch.setattr(
        news_agent,
        "_fetch",
        lambda query: [
            {"title": "AI headline one", "link": "https://example.com/1", "published": "09/11 21:00", "source": "Example"},
            {"title": "AI headline two", "link": "https://example.com/2", "published": "", "source": ""},
        ],
    )
    response = news_agent.handle(req("AI NEWSを教えて"))
    assert response.metadata["status"] == "online"
    assert response.metadata["count"] == 2
    assert "AI headline one" in response.text
    assert "https://example.com/1" in response.text
    assert "AI headline two" in response.text


def test_ai_news_agent_degrades_without_fake_data(monkeypatch):
    def fail(_query):
        raise TimeoutError("feed unavailable")

    monkeypatch.setattr(news_agent, "_fetch", fail)
    response = news_agent.handle(req("AI NEWSを教えて"))
    assert response.metadata["status"] == "degraded"
    assert response.metadata["count"] == 0
    assert "取得できませんでした" in response.text
