import pytest

from core.review import AICompetitionLoop, ReviewFinding, ReviewResult


def test_competition_requires_all_reviewers_to_pass():
    loop = AICompetitionLoop(
        {
            "correctness": lambda artifact: ReviewResult("correctness", True, score=0.9),
            "security": lambda artifact: ReviewResult("security", False, score=0.4),
        }
    )

    decision = loop.review("artifact")

    assert decision.passed is False
    assert decision.score == pytest.approx(0.65)


def test_competition_aggregates_findings_deterministically():
    finding_a = ReviewFinding("correctness", "medium", "issue A")
    finding_b = ReviewFinding("security", "high", "issue B")
    loop = AICompetitionLoop(
        {
            "a": lambda artifact: ReviewResult("a", True, (finding_a,), 1.0),
            "b": lambda artifact: ReviewResult("b", True, (finding_b,), 0.8),
        }
    )

    decision = loop.review("artifact")

    assert decision.findings == (finding_a, finding_b)
    assert decision.score == pytest.approx(0.9)


def test_competition_rejects_invalid_reviewer():
    with pytest.raises(TypeError, match="callable"):
        AICompetitionLoop({"security": object()}).review("artifact")


def test_competition_rejects_invalid_reviewer_result():
    with pytest.raises(TypeError, match="ReviewResult"):
        AICompetitionLoop({"security": lambda artifact: "bad"}).review("artifact")


def test_competition_rejects_blank_reviewer_name():
    with pytest.raises(ValueError, match="reviewer name is required"):
        AICompetitionLoop({" ": lambda artifact: ReviewResult("x", True)}).review("artifact")


def test_competition_rejects_empty_reviewer_registry():
    with pytest.raises(ValueError, match="at least one reviewer"):
        AICompetitionLoop({}).review("artifact")
