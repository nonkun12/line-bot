from agents.english.intents import classify_english_mode, is_english_learning_intent
from agents.english.node import EnglishLearningAgent
from core.agents import AgentRequest


def _request(message: str) -> AgentRequest:
    return AgentRequest(user_id="test-user", message=message, channel="test", metadata={})


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

def test_core_image_command_accepts_word_before_or_after_command():
    from agents.english.core_image import extract_core_image_word, handle_core_image_command

    assert extract_core_image_word("コアイメージ great") == "great"
    assert extract_core_image_word("great コアイメージ") == "great"
    assert "コアイメージ：" in handle_core_image_command("great コアイメージ")


def test_great_has_a_reviewed_local_core_image():
    from agents.english.core_image import explain_core_image

    response = explain_core_image("great")
    assert "基準を大きく上回る" in response
    assert "You did a great job." in response
    assert "無料のローカル解説" in response


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


def test_review_uses_rotating_local_dictionary_words(monkeypatch):
    from agents.english.core_image import get_core_image_quiz_entries

    entries = list(get_core_image_quiz_entries())
    selected = [(entry.word, entry.core_image, entry.example) for entry in entries[:3]]
    monkeypatch.setattr("agents.english.node.select_daily_words", lambda user_id, limit: selected[:limit])
    response = EnglishLearningAgent().handle(_request("復習"))
    expected = " / ".join(word for word, _, _ in selected)
    assert f"今回の復習語: {expected}" in response.text
    assert f"まず「{selected[0][0]}」" in response.text
    assert "今日の復習語: improve / schedule / recommend" not in response.text



def test_vocabulary_rotates_per_user_without_repeating_until_exhausted(monkeypatch, tmp_path):
    from agents.english import quiz_state
    import re

    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "word-history.sqlite3"))
    agent = EnglishLearningAgent()
    first = agent.handle(_request("単語")).text
    second = agent.handle(_request("単語")).text
    words_first = set(re.findall(r"^• ([a-z]+)$", first, re.M))
    words_second = set(re.findall(r"^• ([a-z]+)$", second, re.M))

    assert len(words_first) == 3
    assert len(words_second) == 3
    assert words_first.isdisjoint(words_second)
    assert "確認済みローカル辞書" in first


def test_vocabulary_rotation_is_independent_per_user(monkeypatch, tmp_path):
    import re

    from core.agents import AgentRequest
    from agents.english import quiz_state

    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "user-isolation.sqlite3"))
    agent = EnglishLearningAgent()

    def words_for(user_id):
        request = AgentRequest(
            user_id=user_id,
            message="単語",
            channel="test",
            metadata={},
        )
        response = agent.handle(request).text
        return set(re.findall(r"^• ([a-z]+)$", response, re.M))

    user_a_first = words_for("user-a")
    user_b_first = words_for("user-b")
    user_a_second = words_for("user-a")
    user_b_second = words_for("user-b")

    assert len(user_a_first) == len(user_b_first) == 3
    assert user_a_first == user_b_first
    assert len(user_a_second) == len(user_b_second) == 3
    assert user_a_second.isdisjoint(user_a_first)
    assert user_b_second.isdisjoint(user_b_first)
    assert user_a_second == user_b_second
