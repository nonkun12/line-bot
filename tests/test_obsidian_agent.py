from pathlib import Path

from agents.obsidian.node import obsidian_agent_node


def _state(message: str, vault: Path):
    return {
        "user_id": "test-user",
        "raw_message": message,
        "channel": "test",
        "metadata": {},
        "agent_results": {},
    }


def test_create_note_is_allowed_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = obsidian_agent_node(_state("Obsidianに保存 notes/test.md: hello", tmp_path))
    assert result["agent_results"]["obsidian"]["success"] is True
    assert (tmp_path / "notes" / "test.md").read_text(encoding="utf-8") == "hello"


def test_overwrite_is_blocked_and_append_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    target = tmp_path / "notes" / "test.md"
    target.parent.mkdir()
    target.write_text("one", encoding="utf-8")

    blocked = obsidian_agent_node(_state("Obsidianに保存 notes/test.md: two", tmp_path))
    assert blocked["agent_results"]["obsidian"]["reason"] == "overwrite_blocked"

    appended = obsidian_agent_node(_state("Obsidianに追記 notes/test.md: two", tmp_path))
    assert appended["agent_results"]["obsidian"]["success"] is True
    assert target.read_text(encoding="utf-8") == "onetwo"


def test_read_search_and_list_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.md").write_text("beta", encoding="utf-8")

    read_result = obsidian_agent_node(_state("Obsidianを読む a.md", tmp_path))
    assert read_result["agent_results"]["obsidian"]["text"] == "alpha"

    search_result = obsidian_agent_node(_state("Obsidianで検索 beta", tmp_path))
    assert search_result["agent_results"]["obsidian"]["count"] == 1
    assert "nested/b.md" in search_result["agent_results"]["obsidian"]["text"]

    list_result = obsidian_agent_node(_state("Obsidian一覧", tmp_path))
    assert list_result["agent_results"]["obsidian"]["count"] == 2


def test_unconfigured_vault_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = obsidian_agent_node(_state("Obsidian一覧", tmp_path))
    assert result["agent_results"]["obsidian"]["success"] is False
    assert result["agent_results"]["obsidian"]["reason"] == "vault_not_configured"
