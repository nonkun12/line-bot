from agents.english.core_image_learning import (
    build_core_image_lesson,
    grade_recall,
    next_core_image_word,
)


def test_lesson_connects_core_context_and_usage():
    lesson = build_core_image_lesson("improve")
    assert lesson is not None
    assert lesson.entry.core_image == "今より良い状態へ持っていく"
    assert len(lesson.contexts) >= 2
    assert lesson.contexts[0].sentence == "I want to improve my English."
    assert {item.label for item in lesson.usage} == {"improve", "fix"}
    assert lesson.recall.expected_word == "improve"


def test_recall_is_strict_and_normalized():
    assert grade_recall("improve", " IMPROVE ") is True
    assert grade_recall("improve", "improved") is False
    assert grade_recall("improve", "") is False


def test_unknown_words_fail_closed():
    assert build_core_image_lesson("unknown") is None
    assert next_core_image_word("unknown") == "improve"


def test_next_word_is_bounded_and_deterministic():
    assert next_core_image_word("improve") == "schedule"
    assert next_core_image_word("schedule") == "recommend"
    assert next_core_image_word("recommend") == "improve"
