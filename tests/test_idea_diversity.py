from core.idea_ai import IdeaAgent
from core.idea_evaluator import preserve_unconventional, review_ideas
from core.multi_agent import AgentRole


def test_idea_agent_preserves_unconventional_and_positive_impact():
    ideas = IdeaAgent().propose("Hand-Sign AI", context=("UHIP", "free", "fail-closed"))
    assert len(ideas) == 5
    assert all(item.task.role is AgentRole.IDEA for item in ideas)
    assert all("実装・実行・マージ・デプロイは禁止" in item.task.instruction for item in ideas)
    assert any(item.style == "architecture-leap" for item in ideas)
    assert any(item.novelty >= 4 for item in ideas)
    assert all(item.positive_impact for item in ideas)


def test_idea_agent_covers_five_distinct_opportunity_domains():
    ideas = IdeaAgent().propose("distributed loop")
    assert {idea.domain for idea in ideas} == {
        "product-and-user-value",
        "cross-agent-collaboration",
        "learning-and-quality",
        "new-capabilities",
        "reliability-and-efficiency",
    }
    assert all(idea.assumption_to_test for idea in ideas)
    assert all(idea.success_signal for idea in ideas)
    assert len({idea.domain for idea in ideas}) == len(ideas)


def test_idea_tasks_never_grant_execution_or_override_authority():
    ideas = IdeaAgent().propose("cloud and Mac coordination")
    for idea in ideas:
        assert idea.task.resources == frozenset({"idea-proposals"})
        assert "承認やHOLDの自己解除" in idea.task.instruction
        assert "明示承認" in idea.safety_boundary


def test_diversity_review_does_not_drop_tricky_ideas():
    ideas = IdeaAgent().propose("Loop")
    reviews = review_ideas(ideas)
    kept = preserve_unconventional(ideas)
    assert len(reviews) == len(ideas)
    assert len(kept) == len(ideas)
    assert any(review.unconventional for review in reviews)
    assert all(review.positive_impact_present for review in reviews)


def test_idea_agent_rejects_invalid_input():
    import pytest
    with pytest.raises(ValueError):
        IdeaAgent().propose("")
    with pytest.raises(ValueError):
        IdeaAgent().propose("Loop", limit=6)
    with pytest.raises(TypeError):
        IdeaAgent().propose(123)
    with pytest.raises(TypeError):
        IdeaAgent().propose("Loop", context=("ok", 123))
