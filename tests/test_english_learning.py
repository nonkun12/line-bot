from agents.english.intents import classify_english_mode, is_english_learning_intent
from agents.english.node import EnglishLearningAgent
from core.agents import AgentRequest


def _request(message: str) -> AgentRequest:
    return AgentRequest(user_id="test-user", message=message, channel="test", metadata={})


def test_daily_vocabulary_rotates_without_repeats_before_lexicon_exhaustion(monkeypatch, tmp_path):
    import re
    from agents.english import quiz_state

    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "vocabulary.db"))
    agent = EnglishLearningAgent()
    first = agent.handle(_request("単語")).text
    second = agent.handle(_request("単語")).text

    first_words = set(re.findall(r"^• ([a-z][a-z'-]*)$", first, re.MULTILINE))
    second_words = set(re.findall(r"^• ([a-z][a-z'-]*)$", second, re.MULTILINE))
    assert len(first_words) == len(second_words) == 3
    assert first_words.isdisjoint(second_words)
    assert "コアイメージ" in first and "コアイメージ" in second


def test_quiz_requires_an_active_question(monkeypatch, tmp_path):
    from agents.english import progress

    monkeypatch.setattr(progress, "DB_PATH", str(tmp_path / "quiz.db"))
    agent = EnglishLearningAgent()
    assert is_english_learning_intent("A")
    assert classify_english_mode("A") == "quiz_answer"
    response = agent.handle(_request("A"))
    assert response.metadata["mode"] == "quiz_answer"
    assert "先に「クイズ」" in response.text


def test_quiz_rotates_words_and_grades_the_actual_option(monkeypatch, tmp_path):
    from agents.english import progress
    from agents.english.core_image import get_core_image_quiz_entries
    import re

    monkeypatch.setattr(progress, "DB_PATH", str(tmp_path / "quiz.db"))
    entries = list(get_core_image_quiz_entries())
    agent = EnglishLearningAgent()
    seen = []
    for _ in range(3):
        question = agent.handle(_request("クイズ")).text
        match = re.search(r"次のコアイメージに合う英単語は？\n(.+?)\n\nA\. (\w+)\nB\. (\w+)\nC\. (\w+)", question, re.S)
        assert match, question
        options = {"A": match.group(2), "B": match.group(3), "C": match.group(4)}
        candidates = {entry.word for entry in entries if entry.core_image == match.group(1)}
        correct_word = next(word for word in options.values() if word in candidates)
        assert correct_word in options.values()
        assert correct_word not in seen[-2:]
        seen.append(correct_word)
        answer_label = next(label for label, word in options.items() if word == correct_word)
        result = agent.handle(_request(answer_label)).text
        assert "正解！" in result
        assert correct_word in result
        assert "コアイメージ：" in result
    assert len(set(seen)) == 3


def test_quiz_wrong_answer_reports_dynamic_correct_option(monkeypatch, tmp_path):
    from agents.english import progress
    from agents.english.core_image import get_core_image_quiz_entries
    import re

    monkeypatch.setattr(progress, "DB_PATH", str(tmp_path / "quiz.db"))
    entries = list(get_core_image_quiz_entries())
    agent = EnglishLearningAgent()
    question = agent.handle(_request("クイズ")).text
    match = re.search(r"次のコアイメージに合う英単語は？\n(.+?)\n\nA\. (\w+)\nB\. (\w+)\nC\. (\w+)", question, re.S)
    assert match, question
    options = {"A": match.group(2), "B": match.group(3), "C": match.group(4)}
    candidates = {entry.word for entry in entries if entry.core_image == match.group(1)}
    correct_word = next(word for word in options.values() if word in candidates)
    correct_label = next(label for label, word in options.items() if word == correct_word)
    wrong_label = next(label for label in options if label != correct_label)
    response = agent.handle(_request(wrong_label)).text
    assert "惜しい" in response
    assert f"正解は {correct_label}. {correct_word}" in response

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


def test_learning_profile_remembers_repeated_mistakes(monkeypatch, tmp_path) -> None:
    from agents.english import progress

    class Message:
        content = "Nice work!"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    monkeypatch.setattr(progress, "DB_PATH", str(tmp_path / "english.db"))
    monkeypatch.setattr(
        "agents.english.node.generate_chat_completion",
        lambda **kwargs: Response(),
    )

    agent = EnglishLearningAgent()
    agent.handle(_request("英語AI: I has a pen."))
    agent.handle(_request("英語AI: He have a bike."))

    profile = progress.load_profile("test-user")
    assert profile.turns == 2
    assert profile.level == "beginner"
    assert "subject_verb_agreement" in profile.weak_points


def test_ai_tutor_prompt_uses_profile_context(monkeypatch, tmp_path) -> None:
    from agents.english import progress

    class Message:
        content = "Keep practicing."

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(progress, "DB_PATH", str(tmp_path / "english.db"))
    monkeypatch.setattr("agents.english.node.generate_chat_completion", fake_completion)

    agent = EnglishLearningAgent()
    agent.handle(_request("英語AI: I has a pen."))
    agent.handle(_request("英語AI: Let's practice."))

    prompt = captured["messages"][1]["content"]
    assert "level=beginner" in prompt
    assert "subject_verb_agreement" in prompt
    assert "have/has drill" in prompt
    assert "he/she/it + has" in prompt
