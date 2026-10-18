import json
import sqlite3

import agents.english.quiz_state as quiz_state


def test_daily_words_rotate_without_repeating_until_lexicon_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "english.sqlite3"))
    monkeypatch.setattr(
        quiz_state,
        "_ENTRIES",
        {
            f"word{i}": type("Entry", (), {
                "core_image": f"core {i}",
                "example": f"Example {i}.",
            })()
            for i in range(1, 7)
        },
    )
    first = quiz_state.select_daily_words("user-1", 3)
    second = quiz_state.select_daily_words("user-1", 3)
    assert len(first) == len(second) == 3
    assert {item[0] for item in first}.isdisjoint({item[0] for item in second})
    third = quiz_state.select_daily_words("user-1", 3)
    assert len({item[0] for item in first + second + third}) == 6


def test_quiz_answer_is_not_graded_without_pending_quiz(tmp_path, monkeypatch):
    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "english.sqlite3"))
    assert not quiz_state.has_pending_quiz("user-1")
    assert quiz_state.grade_pending_quiz("user-1", "a") is None


def test_quiz_persists_answer_and_clears_after_grading(tmp_path, monkeypatch):
    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "english.sqlite3"))
    monkeypatch.setattr(
        quiz_state,
        "_ENTRIES",
        {
            "alpha": type("Entry", (), {"core_image": "core alpha", "example": "Alpha example."})(),
            "bravo": type("Entry", (), {"core_image": "core bravo", "example": "Bravo example."})(),
            "charlie": type("Entry", (), {"core_image": "core charlie", "example": "Charlie example."})(),
        },
    )
    prompt = quiz_state.create_quiz("user-1")
    assert "A." in prompt and "B." in prompt and "C." in prompt
    assert quiz_state.has_pending_quiz("user-1")
    with sqlite3.connect(quiz_state.DB_PATH) as conn:
        correct = conn.execute(
            "SELECT correct_option FROM english_pending_quiz WHERE user_id=?", ("user-1",)
        ).fetchone()[0]
    result = quiz_state.grade_pending_quiz("user-1", correct)
    assert result is not None and "正解" in result and "コアイメージ" in result
    assert not quiz_state.has_pending_quiz("user-1")
    assert quiz_state.grade_pending_quiz("user-1", correct) is None


def test_quiz_wrong_answer_explains_correct_word(tmp_path, monkeypatch):
    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "english.sqlite3"))
    monkeypatch.setattr(
        quiz_state,
        "_ENTRIES",
        {
            "alpha": type("Entry", (), {"core_image": "core alpha", "example": "Alpha example."})(),
            "bravo": type("Entry", (), {"core_image": "core bravo", "example": "Bravo example."})(),
            "charlie": type("Entry", (), {"core_image": "core charlie", "example": "Charlie example."})(),
        },
    )
    quiz_state.create_quiz("user-2")
    with sqlite3.connect(quiz_state.DB_PATH) as conn:
        correct = conn.execute(
            "SELECT correct_option FROM english_pending_quiz WHERE user_id=?", ("user-2",)
        ).fetchone()[0]
    wrong = next(letter for letter in "abc" if letter != correct)
    result = quiz_state.grade_pending_quiz("user-2", wrong)
    assert result is not None and "惜しい" in result and "正解は" in result


def test_quiz_uses_words_from_the_most_recently_shown_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(quiz_state, "DB_PATH", str(tmp_path / "english.sqlite3"))
    monkeypatch.setattr(
        quiz_state,
        "_ENTRIES",
        {
            f"word{i}": type("Entry", (), {
                "core_image": f"core {i}",
                "example": f"Example {i}.",
            })()
            for i in range(1, 7)
        },
    )
    shown = {item[0] for item in quiz_state.select_daily_words("user-1", 3)}
    prompt = quiz_state.create_quiz("user-1")
    with sqlite3.connect(quiz_state.DB_PATH) as conn:
        row = conn.execute(
            "SELECT word, options_json FROM english_pending_quiz WHERE user_id=?", ("user-1",)
        ).fetchone()
    assert row[0] in shown
    assert set(json.loads(row[1])).issubset(shown)
    assert all(f". {word}" in prompt for word in json.loads(row[1]))
