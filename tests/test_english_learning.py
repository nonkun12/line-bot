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


def test_explicit_ai_english_tutor_uses_model(monkeypatch) -> None:
    class Message:
        content = "Your correction: I am busy today.\n理由: be動詞を使います。"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    monkeypatch.setattr("agents.english.node.generate_chat_completion", lambda **kwargs: Response())
    response = EnglishLearningAgent().handle(_request("英語AI: I am busy today."))

    assert response.metadata["mode"] == "ai_tutor"
    assert "I am busy today." in response.text


def test_english_sentence_uses_ai_tutor_for_correction(monkeypatch) -> None:
    class Message:
        content = "修正案: I have a pen.\n理由: I has → I have"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    monkeypatch.setattr("agents.english.node.generate_chat_completion", lambda **kwargs: Response())
    response = EnglishLearningAgent().handle(_request("I has a pen"))

    assert response.metadata["mode"] == "correction_ai"
    assert "I have a pen" in response.text


def test_ai_tutor_falls_back_when_model_fails(monkeypatch) -> None:
    def fail(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("agents.english.node.generate_chat_completion", fail)
    response = EnglishLearningAgent().handle(_request("英語AI"))

    assert response.metadata["mode"] == "ai_tutor"
    assert "一時的に使えません" in response.text
