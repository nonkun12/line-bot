from agents.obsidian.intents import normalize_obsidian_command


def test_mcp_obsidian_save_test_is_explicit_obsidian_intent():
    message = "MCPとObsidianの実保存テスト"
    assert normalize_obsidian_command(message) == (
        "Obsidianに追記 LINE-Inbox.md: MCPとObsidianの実保存テスト"
    )


def test_unrelated_mcp_message_is_not_obsidian_intent():
    assert normalize_obsidian_command("MCPについて教えて") is None
