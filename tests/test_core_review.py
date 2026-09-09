import pytest

from core.review import AICompetitionLoop, ReviewFinding, ReviewResult


def test_competition_loop_requires_all_reviewers_to_pass():
    finding = ReviewFinding("security", "high", "unsafe input")
    loop = AICompetitionLoop(
        {
            "correctness": lambda _: ReviewResult("correctness", True, score=0.9),
            "security": lambda _: ReviewResult(
                "security", False, findings=(finding,), score=0.4
            ),
        }
    )

    decision = loop.review("diff")

    assert decision.passed is False
    assert decision.score == pytest.approx(0.65)
    assert decision.findings == (finding,)


def test_competition_loop_passes_when_all_reviewers_pass():
    loop = AICompetitionLoop(
        {
            "correctness": lambda _: ReviewResult("correctness", True, score=0.8),
            "scope": lambda _: ReviewResult("scope", True, score=1.0),
        }
    )

    decision = loop.review("diff")

    assert decision.passed is True
    assert decision.score == pytest.approx(0.9)
    assert decision.findings == ()


@pytest.mark.parametrize("artifact", ["", "   ", None])
def test_competition_loop_rejects_empty_artifact(artifact):
    loop = AICompetitionLoop({"reviewer": lambda _: ReviewResult("r", True)})

    with pytest.raises(ValueError):
        loop.review(artifact)


def test_competition_loop_rejects_missing_reviewers():
    with pytest.raises(ValueError):
        AICompetitionLoop({}).review("diff")


def test_competition_loop_rejects_invalid_reviewer_result():
    loop = AICompetitionLoop({"reviewer": lambda _: "bad"})

    with pytest.raises(TypeError):
        loop.review("diff")
