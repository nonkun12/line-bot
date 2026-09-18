from graph.supervisor import classify_intent


def test_future_agent_intents_route_to_dedicated_agents():
    assert classify_intent("英語を勉強したい") == "english_learning"
    assert classify_intent("AAPLの株価を教えて") == "stocks"
    assert classify_intent("AIニュースを教えて") == "ai_news"
    assert classify_intent("AIスピーカーで話して") == "voice"
    assert classify_intent("求人を探したい") == "jobs"


def test_unsupported_message_falls_back_safely():
    assert classify_intent("これは登録されていない依頼です") == "unsupported"



def test_job_seeking_traverses_main_langgraph():
    from graph.graph import build_graph

    graph = build_graph()
    result = graph.invoke({
        "user_id": "test-user",
        "raw_message": "求人を探したい",
        "channel": "test",
        "metadata": {},
        "agent_results": {},
    })

    assert result["intent"] == "jobs"
    assert result["next_agent"] == "job_seeking"
    assert "job_seeking" in result["agent_results"]
    assert result["final_reply"]
