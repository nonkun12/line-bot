from agents.news.intents import is_ai_news_intent
from agents.stocks.intents import is_stock_intent
from agents.voice.intents import is_voice_intent
from graph.supervisor import classify_intent


def test_stock_intent_avoids_english_substring_false_positives():
    assert not is_stock_intent("Stockholmの天気")
    assert not is_stock_intent("invoiceを確認して")
    assert is_stock_intent("AAPL stock price")
    assert is_stock_intent("7203の株価")


def test_voice_intent_avoids_english_substring_false_positives():
    assert not is_voice_intent("invoiceを確認して")
    assert is_voice_intent("voice assistantで話して")
    assert is_voice_intent("AIスピーカーで話して")


def test_ai_news_intent_requires_news_phrase():
    assert not is_ai_news_intent("AI newsletterを要約して")
    assert is_ai_news_intent("AI newsを教えて")
    assert is_ai_news_intent("AIニュースを教えて")


def test_supervisor_uses_feature_boundaries():
    assert classify_intent("Stockholmの天気") == "weather"
    assert classify_intent("invoiceを確認して") == "unsupported"
    assert classify_intent("AI newsを教えて") == "ai_news"
    assert classify_intent("voice assistantで話して") == "voice"


def test_ai_news_boundary_handles_japanese_suffixes():
    assert is_ai_news_intent("AI newsを見せて")
    assert is_ai_news_intent("AI newsで最新情報")
    assert not is_ai_news_intent("AI newsletterを見せて")
