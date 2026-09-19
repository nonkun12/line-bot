from agents.english.intents import classify_english_mode, is_english_learning_intent
from agents.english.node import EnglishLearningAgent
from core.agents import AgentRequest


def _request(message: str) -> AgentRequest:
    return AgentRequest(user_id="test-user", message=message, channel="test", metadata={})


def test_quiz_answer_is_routed_and_graded():
    agent = EnglishLearningAgent()
    assert is_english_learning_intent("A")
    assert classify_english_mode("A") == "quiz_answer"
    response = agent.handle(_request("A"))
    assert response.metadata["mode"] == "quiz_answer"
    assert "正解" in response.text


def test_wrong_quiz_answer_is_explained():
    response = EnglishLearningAgent().handle(_request("C"))
    assert "正解は A" in response.text


def test_common_english_sentence_gets_correction_feedback():
    agent = EnglishLearningAgent()
    request = _request("I am busy today.")
    assert agent.can_handle(request)
    response = agent.handle(request)
    assert response.metadata["mode"] == "correction"
    assert "英文チェック" in response.text
    assert "I am busy today." in response.text


def test_unrelated_japanese_is_not_claimed_as_english_follow_up():
    request = _request("今日は忙しいです")
    assert not EnglishLearningAgent().can_handle(request)


def test_common_grammar_error_gets_a_concrete_correction() -> None:
    response = EnglishLearningAgent().handle(_request("I has a pen"))
    assert response.metadata["mode"] == "correction"
    assert "修正案: I have a pen" in response.text
    assert "文法OK" not in response.text


def test_interview_and_business_modes_are_routed() -> None:
    agent = EnglishLearningAgent()
    interview = agent.handle(_request("英語面接"))
    business = agent.handle(_request("ビジネス英語"))
    assert interview.metadata["mode"] == "interview"
    assert "Tell me about yourself" in interview.text
    assert business.metadata["mode"] == "business"
    assert "ビジネス英語" in business.text


def test_unknown_english_sentence_does_not_claim_full_grammar_validation() -> None:
    response = EnglishLearningAgent().handle(_request("The weather is nice today."))
    assert response.metadata["mode"] == "correction"
    assert "明確な基本ルール違反を検出できませんでした" in response.text
