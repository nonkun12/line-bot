import json
from unittest.mock import MagicMock

from agents.memory.handlers import (
    handle_memory_message,
)


def test_handle_save_memory_saves_name():
    call_mcp_tool = MagicMock(return_value="saved")

    result = handle_memory_message(
        "覚えて 私の名前は太郎です",
        "user123",
        call_mcp_tool,
    )

    assert result == "saved"
    call_mcp_tool.assert_called_once_with(
        "save_memory",
        {
            "user_id": "user123",
            "key": "name",
            "value": "太郎",
        },
    )


def test_handle_save_memory_exclusion_does_not_call_save():
    call_mcp_tool = MagicMock()

    result = handle_memory_message(
        "明日5時に覚えて",
        "user123",
        call_mcp_tool,
    )

    assert result is None
    call_mcp_tool.assert_not_called()


def test_handle_get_name_returns_parsed_name():
    name_json = json.dumps({"value": "太郎"})
    call_mcp_tool = MagicMock(return_value=name_json)

    result = handle_memory_message(
        "私の名前は？",
        "user123",
        call_mcp_tool,
    )

    assert result == "あなたの名前は 太郎 です。"
    call_mcp_tool.assert_called_once_with(
        "get_memory",
        {
            "user_id": "user123",
            "key": "name",
        },
    )


def test_handle_delete_memory_calls_delete():
    call_mcp_tool = MagicMock(return_value="deleted")

    result = handle_memory_message(
        "名前を忘れて",
        "user123",
        call_mcp_tool,
    )

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_memory",
        {
            "user_id": "user123",
            "key": "name",
        },
    )


def test_handle_delete_memory_calls_delete_for_delete_request():
    call_mcp_tool = MagicMock(return_value="deleted")

    result = handle_memory_message(
        "名前を削除して",
        "user123",
        call_mcp_tool,
    )

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_memory",
        {
            "user_id": "user123",
            "key": "name",
        },
    )


def test_handle_delete_all_memory_returns_confirmation():
    call_mcp_tool = MagicMock()

    result = handle_memory_message(
        "記憶全部削除",
        "user123",
        call_mcp_tool,
    )

    assert result == "記憶をすべて削除しますか？「はい」と送ってください"
    call_mcp_tool.assert_not_called()


def test_handle_delete_all_memory_confirmation_calls_delete_all_memory():
    call_mcp_tool = MagicMock(return_value="deleted all")

    first = handle_memory_message(
        "記憶全部削除",
        "user456",
        call_mcp_tool,
    )
    assert first == "記憶をすべて削除しますか？「はい」と送ってください"

    second = handle_memory_message(
        "はい",
        "user456",
        call_mcp_tool,
    )

    assert second == "deleted all"
    call_mcp_tool.assert_called_with(
        "delete_all_memory",
        {
            "user_id": "user456",
        },
    )


def test_handle_get_all_memory_returns_name_from_memory_list():
    memories_json = json.dumps([
        {"key": "memory", "value": "some note"},
        {"key": "name", "value": "太郎"},
    ])
    call_mcp_tool = MagicMock(return_value=memories_json)

    result = handle_memory_message(
        "名前を教えて",
        "user123",
        call_mcp_tool,
    )

    assert result == "あなたの名前は 太郎 です。"
    call_mcp_tool.assert_called_once_with(
        "get_all_memory",
        {
            "user_id": "user123",
        },
    )
