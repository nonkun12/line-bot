import pytest

from core.review import AICompetitionLoop, ReviewerRegistry, ReviewResult


def test_reviewer_registry_registers_and_lists_reviewers():
    registry = ReviewerRegistry()
    reviewer = lambda artifact: ReviewResult("security", True, score=1.0)

    registry.register("security", reviewer)

    assert registry.names() == ("security",)
    assert registry.get("security") is reviewer


def test_reviewer_registry_rejects_duplicate_names():
    reviewer = lambda artifact: ReviewResult("security", True)
    registry = ReviewerRegistry({"security": reviewer})

    with pytest.raises(ValueError, match="already registered"):
        registry.register("security", reviewer)


def test_reviewer_registry_rejects_invalid_reviewer():
    registry = ReviewerRegistry()

    with pytest.raises(TypeError, match="reviewer must be callable"):
        registry.register("security", object())


def test_competition_loop_accepts_reviewer_registry():
    registry = ReviewerRegistry(
        {
            "correctness": lambda artifact: ReviewResult("correctness", True, score=0.9),
            "security": lambda artifact: ReviewResult("security", True, score=0.8),
        }
    )

    decision = AICompetitionLoop(registry).review("artifact")

    assert decision.passed is True
    assert decision.score == pytest.approx(0.85)


def test_competition_loop_exposes_registry_for_later_extension():
    registry = ReviewerRegistry()
    loop = AICompetitionLoop({"correctness": lambda artifact: ReviewResult("correctness", True)})

    loop.reviewers.register(
        "scope",
        lambda artifact: ReviewResult("scope", True),
    )

    assert loop.reviewers.names() == ("correctness", "scope")
    assert registry.names() == ()
