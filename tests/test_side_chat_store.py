from __future__ import annotations

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
