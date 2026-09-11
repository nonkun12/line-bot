from graph.supervisor import classify_intent


def test_future_agent_intents_route_to_dedicated_agents():
    assert classify_intent("英語を勉強したい") == "english_learning"
    assert classify_intent("AAPLの株価を教えて") == "stocks"
    assert classify_intent("AIニュースを教えて") == "ai_news"
    assert classify_intent("AIスピーカーで話して") == "voice"


def test_unsupported_message_falls_back_safely():
    assert classify_intent("これは登録されていない依頼です") == "unsupported"
