from core.agents import AgentRequest
from graph.core_registry import build_core_agent_registry


def test_organizer_is_registered_and_resolves_explicit_request():
    registry = build_core_agent_registry()
    assert "obsidian_organizer" in registry.names()

    request = AgentRequest(
        user_id="test",
        message="Obsidian整理: 残件を整理する",
        channel="test",
    )
    agent = registry.resolve(request)
    assert agent is not None
    assert agent.name == "obsidian_organizer"


def test_organizer_response_is_proposal_only():
    registry = build_core_agent_registry()
    request = AgentRequest(
        user_id="test",
        message="Obsidian整理: 残件を整理する",
        channel="test",
    )
    response = registry.get("obsidian_organizer").handle(request)

    assert response.metadata["proposal_only"] is True
    assert response.metadata["requires_human_approval"] is True
    assert response.metadata["destructive"] is False


def test_organizer_does_not_handle_normal_obsidian_save():
    registry = build_core_agent_registry()
    request = AgentRequest(
        user_id="test",
        message="Obsidianに保存 note.md: hello",
        channel="test",
    )
    assert registry.get("obsidian_organizer").can_handle(request) is False
