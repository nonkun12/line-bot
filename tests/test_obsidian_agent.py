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


def test_obisidian_routes_through_current_core_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    from graph.supervisor import supervisor_node
    from graph.core_graph import build_current_core_graph

    state = supervisor_node({
        "user_id": "test-user",
        "raw_message": "Obsidianに保存 notes/graph.md: hello",
        "channel": "test",
        "metadata": {},
        "agent_results": {},
    })
    result = build_current_core_graph().invoke(state)
    assert result["intent"] == "obsidian"
    assert result["next_agent"] == "obsidian"
    assert result["agent_results"]["obsidian"]["text"].startswith("Obsidianに保存しました")


def test_natural_record_command_appends_to_default_note(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = obsidian_agent_node(
        _state("Obsidianに「自然文Bridgeテスト」と記録して", tmp_path)
    )
    assert result["agent_results"]["obsidian"]["success"] is True
    assert result["agent_results"]["obsidian"]["operation"] == "append"
    target = tmp_path / "LINE-Inbox.md"
    assert target.read_text(encoding="utf-8") == "自然文Bridgeテスト"


def test_line_note_natural_record_command_appends_to_default_note(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = obsidian_agent_node(
        _state("メモをObsidianに保存して「MCPとObsidianの実保存テスト」と書いて", tmp_path)
    )
    assert result["agent_results"]["obsidian"]["success"] is True
    assert result["agent_results"]["obsidian"]["operation"] == "append"
    target = tmp_path / "LINE-Inbox.md"
    assert target.read_text(encoding="utf-8") == "MCPとObsidianの実保存テスト"


def test_explicit_idea_is_routed_and_saved_as_new_card(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    from graph.supervisor import supervisor_node

    message = "アイデア: LINEから発展案を自動生成する"
    state = supervisor_node({
        "user_id": "test-user",
        "raw_message": message,
        "channel": "test",
        "metadata": {},
        "agent_results": {},
    })
    assert state["intent"] == "obsidian"
    assert state["next_agent"] == "obsidian"

    result = obsidian_agent_node(_state(message, tmp_path))
    metadata = result["agent_results"]["obsidian"]
    assert metadata["success"] is True
    assert metadata["operation"] == "create"
    note = tmp_path / metadata["path"]
    assert note.is_file()
    saved = note.read_text(encoding="utf-8")
    assert "原案（原文・変更禁止）" in saved
    assert "LINEから発展案を自動生成する" in saved
    assert "発展案（自動生成・未検証）" in saved
    assert "- execution_approval: pending" in saved


def test_repeated_idea_capture_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    message = "アイデア: 同じ入力の重複保存を防ぐ"
    first = obsidian_agent_node(_state(message, tmp_path))
    first_meta = first["agent_results"]["obsidian"]
    assert first_meta["success"] is True
    note = tmp_path / first_meta["path"]
    original_contents = note.read_text(encoding="utf-8")

    second = obsidian_agent_node(_state(message, tmp_path))
    second_meta = second["agent_results"]["obsidian"]
    assert second_meta["success"] is True
    assert second_meta["duplicate"] is True
    assert note.read_text(encoding="utf-8") == original_contents
    assert len(list((tmp_path / "Ideas" / "Inbox").glob("IDEA-*.md"))) == 1


def test_idea_capture_queues_when_cloud_has_no_vault(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    captured = {}

    def fake_enqueue(user_id, message):
        captured.update(user_id=user_id, message=message)
        return 51

    monkeypatch.setattr("core.obsidian_bridge.enqueue_obsidian_request", fake_enqueue)
    result = obsidian_agent_node(_state("アイデア: Mac側で安全に保存する", tmp_path))
    metadata = result["agent_results"]["obsidian"]

    assert metadata["success"] is True
    assert metadata["operation"] == "queued"
    assert metadata["status"] == "pending"
    assert metadata["job_id"] == 51
    assert captured["message"] == "アイデア: Mac側で安全に保存する"
