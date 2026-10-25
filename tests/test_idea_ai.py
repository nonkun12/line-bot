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


from datetime import datetime, timezone

from core.idea_ai import build_idea_card, idea_command_to_obsidian_command, parse_idea_command


def test_explicit_capture_creates_stable_card_with_development_ideas():
    focus = "LINEからアイデアをObsidianに保存する"
    card = build_idea_card(focus, created_at=datetime(2026, 10, 26, tzinfo=timezone.utc))

    assert card["path"].startswith("Ideas/Inbox/IDEA-")
    assert card["focus"] == focus
    assert card["execution_approval"] == "pending"
    assert len(card["proposals"]) == 5
    assert "~~~text\n" + focus + "\n~~~" in card["markdown"]
    assert "発展案（自動生成・未検証）" in card["markdown"]
    assert "関連アイデア候補（自動生成・未検証）" in card["markdown"]
    assert "- execution_approval: pending" in card["markdown"]


def test_only_explicit_prefix_is_captured():
    assert parse_idea_command("アイデア: 新しい分散AIを考える") == "新しい分散AIを考える"
    assert parse_idea_command("新しい分散AIを考える") is None
    assert parse_idea_command("アイデア:   ") is None


def test_capture_adapter_uses_existing_guarded_obsidian_format():
    command = idea_command_to_obsidian_command("アイデア: 発展案を自動生成する")
    assert command is not None
    assert command.startswith("Obsidianに保存 Ideas/Inbox/IDEA-")
    assert "execution_approval: pending" in command
    assert idea_command_to_obsidian_command("単なる会話") is None


def test_card_rejects_oversized_input_and_invalid_source():
    import pytest

    with pytest.raises(ValueError, match="4000"):
        build_idea_card("x" * 4_001)
    with pytest.raises(ValueError, match="source"):
        build_idea_card("idea", source="remote-paid-api")
