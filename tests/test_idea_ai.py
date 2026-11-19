from core.idea_ai import IdeaAgent
from core.multi_agent import AgentRole

def test_idea_agent_is_bounded_and_non_executing():
    ideas = IdeaAgent().propose("Hand-Sign AI", context=("UHIP", "free", "fail-closed"))
    assert len(ideas) == 5
    assert all(item.task.role is AgentRole.IDEA for item in ideas)
    assert all("No implementation, execution, merge, deploy" in item.task.instruction for item in ideas)

def test_idea_agent_rejects_invalid_input():
    import pytest
    with pytest.raises(ValueError):
        IdeaAgent().propose("")
    with pytest.raises(ValueError):
        IdeaAgent().propose("Loop", limit=6)
