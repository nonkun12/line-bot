from __future__ import annotations

import pytest

from agents.english import vocabulary_workflow as workflow


@pytest.fixture
def isolated_vocabulary_db(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "DB_PATH", str(tmp_path / "english-test.sqlite3"))


def _entry(word: str) -> dict:
    return {
        "word": word,
        "pronunciation": "テスト",
        "core_image": "意味をつかむための確認済みイメージ",
        "parts": "語源は未確認。語形成を断定しない。",
        "related": ["related item", "another item"],
        "example": "This is a reviewed example.",
        "note": "Reviewed locally.",
    }


def test_candidate_submission_is_pending_and_not_live(isolated_vocabulary_db):
    from agents.english.core_image import explain_core_image, get_core_image_quiz_entries

    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")

    assert receipt.status == "pending"
    assert receipt.word == "novelwordxyz"
    assert "説明を保留" in explain_core_image("novelwordxyz")
    assert "novelwordxyz" not in {entry.word for entry in get_core_image_quiz_entries()}
    assert workflow.list_pending_candidates()[0]["candidate_id"] == receipt.candidate_id


def test_registry_and_pending_queue_reject_duplicates(isolated_vocabulary_db):
    with pytest.raises(ValueError, match="previously registered"):
        workflow.submit_word_candidate("inspect", "learner-1")

    workflow.submit_word_candidate("novelwordxyz", "learner-1")
    with pytest.raises(ValueError, match="already pending"):
        workflow.submit_word_candidate("NOVELWORDXYZ", "learner-2")


def test_approval_requires_authorized_reviewer(isolated_vocabulary_db):
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")

    with pytest.raises(PermissionError):
        workflow.approve_word_candidate(receipt.candidate_id, _entry(receipt.word), "reviewer")


def test_approved_entry_is_atomically_added_to_explanation_and_quiz(isolated_vocabulary_db):
    from agents.english.core_image import explain_core_image, get_core_image_quiz_entries

    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    approved = workflow.approve_word_candidate(
        receipt.candidate_id,
        _entry(receipt.word),
        "reviewer-1",
        authorize_reviewer=lambda reviewer: reviewer == "reviewer-1",
    )

    assert approved == "novelwordxyz"
    assert "意味をつかむための確認済みイメージ" in explain_core_image(approved)
    assert approved in {entry.word for entry in get_core_image_quiz_entries()}
    assert workflow.list_pending_candidates() == ()


def test_approval_rejects_mismatched_or_incomplete_entry(isolated_vocabulary_db):
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    with pytest.raises(ValueError, match="candidate"):
        workflow.approve_word_candidate(
            receipt.candidate_id,
            _entry("differentword"),
            "reviewer-1",
            authorize_reviewer=lambda _: True,
        )

    invalid = _entry(receipt.word)
    invalid["related"] = "not-a-list"
    with pytest.raises(ValueError, match="related must"):
        workflow.approve_word_candidate(
            receipt.candidate_id,
            invalid,
            "reviewer-1",
            authorize_reviewer=lambda _: True,
        )


def test_line_command_submits_candidate_without_approving_it(isolated_vocabulary_db):
    from agents.english.node import EnglishLearningAgent
    from core.agents import AgentRequest

    request = AgentRequest(
        user_id="learner-1",
        message="単語追加: novelwordxyz",
        channel="line",
        metadata={},
    )
    response = EnglishLearningAgent().handle(request)

    assert "審査待ち" in response.text
    assert "学習辞書には追加されません" in response.text
    assert workflow.list_pending_candidates()[0]["word"] == "novelwordxyz"


def test_rejected_candidate_cannot_be_reopened(isolated_vocabulary_db):
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    workflow.reject_word_candidate(
        receipt.candidate_id,
        "reviewer-1",
        "not suitable for the current curriculum",
        authorize_reviewer=lambda reviewer: reviewer == "reviewer-1",
    )
    with pytest.raises(ValueError, match="already reviewed"):
        workflow.submit_word_candidate("novelwordxyz", "learner-2")


def test_approved_word_cannot_be_submitted_again(isolated_vocabulary_db):
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    workflow.approve_word_candidate(
        receipt.candidate_id,
        _entry(receipt.word),
        "reviewer-1",
        authorize_reviewer=lambda _: True,
    )
    with pytest.raises(ValueError, match="previously registered|already approved"):
        workflow.submit_word_candidate("novelwordxyz", "learner-2")


def test_approved_word_enters_daily_rotation(isolated_vocabulary_db, monkeypatch):
    from agents.english import quiz_state

    monkeypatch.setattr(quiz_state, "DB_PATH", workflow.DB_PATH)
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    workflow.approve_word_candidate(
        receipt.candidate_id,
        _entry(receipt.word),
        "reviewer-1",
        authorize_reviewer=lambda _: True,
    )

    words = quiz_state._lexicon()
    assert "novelwordxyz" in {word for word, _, _ in words}

def test_quiz_grading_resolves_approved_dynamic_word(isolated_vocabulary_db, monkeypatch):
    from agents.english import quiz_state

    monkeypatch.setattr(quiz_state, "DB_PATH", workflow.DB_PATH)
    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    workflow.approve_word_candidate(
        receipt.candidate_id,
        _entry(receipt.word),
        "reviewer-1",
        authorize_reviewer=lambda _: True,
    )

    with quiz_state._connect() as conn:
        conn.execute(
            "INSERT INTO english_word_history(user_id, word, shown_at) VALUES (?, ?, ?)",
            ("learner-1", receipt.word, "2026-11-10T00:00:00+00:00"),
        )
    quiz_state.create_quiz("learner-1")
    with quiz_state._connect() as conn:
        pending = conn.execute(
            "SELECT word, correct_option FROM english_pending_quiz WHERE user_id=?",
            ("learner-1",),
        ).fetchone()
    assert pending[0] == receipt.word
    correct = pending[1]

    result = quiz_state.grade_pending_quiz("learner-1", correct)
    assert result is not None
    assert "意味をつかむための確認済みイメージ" in result

def test_line_core_image_command_reaches_reviewed_dictionary(isolated_vocabulary_db):
    from agents.english.node import EnglishLearningAgent
    from core.agents import AgentRequest

    response = EnglishLearningAgent().handle(
        AgentRequest(
            user_id="learner-1",
            message="コアイメージ inspect",
            channel="line",
            metadata={},
        )
    )
    assert "inspect" in response.text
    assert "コアイメージ：" in response.text
    assert response.metadata["mode"] == "core_image"


def test_line_quiz_uses_approved_dynamic_words(isolated_vocabulary_db, monkeypatch):
    from agents.english import quiz
    from agents.english.node import EnglishLearningAgent
    from core.agents import AgentRequest

    receipt = workflow.submit_word_candidate("novelwordxyz", "learner-1")
    workflow.approve_word_candidate(
        receipt.candidate_id,
        _entry(receipt.word),
        "reviewer-1",
        authorize_reviewer=lambda _: True,
    )
    monkeypatch.setattr(
        quiz.random,
        "choice",
        lambda pool: next(item for item in pool if item.word == receipt.word),
    )
    response = EnglishLearningAgent().handle(
        AgentRequest(user_id="learner-1", message="クイズ", channel="line", metadata={})
    )
    assert "novelwordxyz" in response.text
