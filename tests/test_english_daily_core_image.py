from datetime import date

from agents.english.core_image import _ENTRIES
from agents.english.node import _daily_quiz, _daily_words, _grade_quiz


def test_daily_words_come_from_reviewed_dictionary_and_change_by_day():
    first = _daily_words(date(2026, 10, 15))
    second = _daily_words(date(2026, 10, 16))
    assert len(first) == len(second) == 3
    assert len({entry.word for entry in first}) == 3
    assert all(entry.word in _ENTRIES for entry in first + second)
    assert {entry.word for entry in first}.isdisjoint({entry.word for entry in second})


def test_daily_vocabulary_is_stable_for_same_japan_date():
    day = date(2026, 10, 16)
    assert [entry.word for entry in _daily_words(day)] == [
        entry.word for entry in _daily_words(day)
    ]


def test_quiz_key_matches_rotated_choices_and_grading():
    day = date(2026, 10, 16)
    words, choices, answer = _daily_quiz(day)
    assert choices["abc".index(answer)].word == words[0].word
    assert _grade_quiz(answer, day).startswith("✅ 正解！")
    wrong = next(letter for letter in "abc" if letter != answer)
    assert _grade_quiz(wrong, day).startswith("❌ 惜しい！")
