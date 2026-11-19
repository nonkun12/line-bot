from core.idea_ai import IdeaAgent
from core.idea_handoff import IdeaAcceptance, handoff_idea
from core.multi_agent import AgentRole

def test_rejected_idea_never_reaches_implementer():
    idea = IdeaAgent().propose("Hand-Sign AI", limit=1)[0]
    assert handoff_idea(idea, IdeaAcceptance(False, "not ready")) is None

def test_accepted_idea_handoff_is_explicit():
    idea = IdeaAgent().propose("Hand-Sign AI", limit=1)[0]
    task = handoff_idea(idea, IdeaAcceptance(True, "human-approved"))
    assert task is not None
    assert task.role is AgentRole.IMPLEMENTER
    assert "human-approved" in task.instruction
