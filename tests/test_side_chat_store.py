from __future__ import annotations

import sqlite3

import pytest

from core.side_chat_store import (
    MAX_ACTIVE_SIDE_CHATS,
    SideChatError,
    SideChatNotFound,
    SideChatStore,
)


@pytest.fixture
def store(tmp_path):
    instance = SideChatStore(tmp_path / "side-chats.sqlite3")
    instance.initialize()
    return instance


def test_side_chats_keep_histories_separate_and_scoped_to_owner(store):
    first = store.create("user-a", "Research", "Compare options")
    second = store.create("user-a", "Creative", "Explore a story")

    store.append_message("user-a", first["id"], "user", "Find a concept")
    store.append_message("user-a", first["id"], "assistant", "Three concepts")
    store.append_message("user-a", second["id"], "user", "Write a scene")

    first_loaded = store.get("user-a", first["id"])
    second_loaded = store.get("user-a", second["id"])
    assert [item["content"] for item in first_loaded["messages"]] == [
        "Find a concept",
        "Three concepts",
    ]
    assert [item["content"] for item in second_loaded["messages"]] == ["Write a scene"]
    assert [item["id"] for item in store.list_for_user("user-b")] == []


def test_project_and_workspace_context_are_scoped_and_listable(store):
    chat = store.create(
        "user-a",
        "Story",
        "Develop episode one",
        project_id="STAR-NIGHT",
        workspace_id="story",
        context_refs=[
            "docs/creative-worlds/star-night/series-bible.md",
            "docs/creative-worlds/star-night/game-story-graph.json",
        ],
    )
    assert chat["project_id"] == "STAR-NIGHT"
    assert chat["workspace_id"] == "story"
    assert chat["context_refs"] == [
        "docs/creative-worlds/star-night/series-bible.md",
        "docs/creative-worlds/star-night/game-story-graph.json",
    ]
    assert [item["id"] for item in store.list_for_project("user-a", "STAR-NIGHT")] == [
        chat["id"]
    ]
    assert store.list_for_project("user-b", "STAR-NIGHT") == []
    assert store.list_for_project("user-a", "OTHER-PROJECT") == []


def test_project_scope_and_context_refs_are_validated(store):
    with pytest.raises(SideChatError, match="project_id"):
        store.create("user-a", "Bad project", project_id="../other")
    with pytest.raises(SideChatError, match="workspace_id"):
        store.create("user-a", "Bad workspace", workspace_id="story/music")
    with pytest.raises(SideChatError, match="context_refs"):
        store.create("user-a", "Too many refs", context_refs=["x"] * 21)
    with pytest.raises(SideChatError, match="context_ref"):
        store.create("user-a", "Bad ref", context_refs=[" "])
    with pytest.raises(SideChatError, match="maximum length"):
        store.create("user-a", "Long ref", context_refs=["x" * 513])


def test_existing_database_is_migrated_without_losing_side_chats(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE side_chats ("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, "
        "purpose TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO side_chats(id,user_id,title) VALUES ('legacy-id','user-a','Legacy')"
    )
    conn.commit()
    conn.close()

    migrated = SideChatStore(path)
    migrated.initialize()
    loaded = migrated.get("user-a", "legacy-id")
    assert loaded["title"] == "Legacy"
    assert loaded["project_id"] is None
    assert loaded["workspace_id"] is None
    assert loaded["context_refs"] == []


def test_user_cannot_read_or_append_to_another_users_side_chat(store):
    chat = store.create("owner", "Private")
    with pytest.raises(SideChatNotFound):
        store.get("intruder", chat["id"])
    with pytest.raises(SideChatNotFound):
        store.append_message("intruder", chat["id"], "user", "steal history")


def test_active_side_chat_limit_is_enforced(store):
    for index in range(MAX_ACTIVE_SIDE_CHATS):
        store.create("user-a", f"Chat {index}")
    with pytest.raises(SideChatError, match="maximum active"):
        store.create("user-a", "One too many")


def test_invalid_roles_and_oversized_messages_are_rejected(store):
    chat = store.create("user-a", "Safe")
    with pytest.raises(SideChatError, match="role"):
        store.append_message("user-a", chat["id"], "system", "inject instructions")
    with pytest.raises(SideChatError, match="maximum length"):
        store.append_message("user-a", chat["id"], "user", "x" * 12001)


def test_handoff_is_pending_and_never_mutates_main_conversation(store):
    chat = store.create("user-a", "Design")
    store.append_message("user-a", chat["id"], "assistant", "A useful finding")
    handoff = store.create_handoff("user-a", chat["id"], "Proposed summary")
    assert handoff["status"] == "pending"
    assert store.get("user-a", chat["id"])["messages"][0]["content"] == "A useful finding"


def test_handoff_requires_explicit_owner_decision(store):
    chat = store.create("user-a", "Review")
    handoff = store.create_handoff("user-a", chat["id"], "Review result")
    with pytest.raises(SideChatNotFound):
        store.set_handoff_status("other-user", handoff["id"], "accepted")
    accepted = store.set_handoff_status("user-a", handoff["id"], "accepted")
    assert accepted["status"] == "accepted"
    with pytest.raises(SideChatNotFound):
        store.set_handoff_status("user-a", handoff["id"], "dismissed")


def test_invalid_user_and_title_are_rejected(store):
    with pytest.raises(SideChatError):
        store.create("", "Title")
    with pytest.raises(SideChatError):
        store.create("user-a", " ")


def test_archiving_releases_active_slot_and_preserves_history(store):
    first = store.create("user-a", "First")
    second = store.create("user-a", "Second")
    store.append_message("user-a", first["id"], "user", "keep this history")
    archived = store.archive("user-a", first["id"])
    assert archived["status"] == "archived"
    third = store.create("user-a", "Third")
    assert third["status"] == "active"
    assert store.get("user-a", first["id"])["messages"][0]["content"] == "keep this history"
    with pytest.raises(SideChatNotFound):
        store.archive("other-user", second["id"])
