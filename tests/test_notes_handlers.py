from unittest.mock import MagicMock

from agents.notes.handlers import (
    handle_auto_save_note,
    handle_delete_note,
    handle_list_notes,
    handle_natural_note_search,
    handle_save_note,
    handle_search_notes,
)


def test_handle_list_notes_calls_search_notes():
    call_mcp_tool = MagicMock(return_value="list result")

    result = handle_list_notes("user123", call_mcp_tool)

    assert result == "list result"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {"user_id": "user123", "keyword": ""},
    )


def test_handle_search_notes_success():
    call_mcp_tool = MagicMock(return_value="search result")

    result = handle_search_notes("メモ検索 テニス", "user123", call_mcp_tool)

    assert result == "search result"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {"user_id": "user123", "keyword": "テニス"},
    )


def test_handle_search_notes_without_keyword():
    call_mcp_tool = MagicMock()

    result = handle_search_notes("メモ検索", "user123", call_mcp_tool)

    assert result == "検索キーワードを指定してください。\n例: メモ検索 テニス"
    call_mcp_tool.assert_not_called()


def test_handle_natural_note_search_my_notes():
    call_mcp_tool = MagicMock(return_value="my notes")

    result = handle_natural_note_search("私のメモ", "user123", call_mcp_tool)

    assert result == "my notes"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {"user_id": "user123", "keyword": ""},
    )


def test_handle_natural_note_search_keyword_extraction():
    call_mcp_tool = MagicMock(return_value="search result")

    result = handle_natural_note_search("テニスのメモを探して", "user123", call_mcp_tool)

    assert result == "search result"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {"user_id": "user123", "keyword": "テニスの"},
    )


def test_handle_save_note_classifies_category():
    call_mcp_tool = MagicMock(return_value="saved")

    result = handle_save_note("メモして Pythonの勉強", "user123", call_mcp_tool)

    assert result == "saved"
    call_mcp_tool.assert_called_once_with(
        "save_note",
        {
            "user_id": "user123",
            "title": "LINEメモ",
            "body": "Pythonの勉強",
            "category": "技術",
        },
    )


def test_handle_auto_save_note_matches():
    call_mcp_tool = MagicMock(return_value="auto saved")

    result = handle_auto_save_note("明日旅行する予定", "user123", call_mcp_tool)

    assert result == "auto saved"
    call_mcp_tool.assert_called_once_with(
        "save_note",
        {
            "user_id": "user123",
            "title": "自動メモ",
            "body": "明日旅行する予定",
            "category": "一般",
        },
    )


def test_handle_auto_save_note_no_match():
    call_mcp_tool = MagicMock()

    result = handle_auto_save_note("こんにちは、元気ですか", "user123", call_mcp_tool)

    assert result is None
    call_mcp_tool.assert_not_called()


def test_handle_delete_note_natural():
    call_mcp_tool = MagicMock(return_value="deleted")

    result = handle_delete_note("5番のメモを削除して", "user123", call_mcp_tool)

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_note",
        {"user_id": "user123", "id": "5"},
    )


def test_handle_delete_note_explicit():
    call_mcp_tool = MagicMock(return_value="deleted")

    result = handle_delete_note("メモ削除10", "user123", call_mcp_tool)

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_note",
        {"user_id": "user123", "id": "10"},
    )


def test_handle_delete_note_explicit_zenkaku():
    call_mcp_tool = MagicMock(return_value="deleted")

    result = handle_delete_note("メモ削除２５", "user123", call_mcp_tool)

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_note",
        {"user_id": "user123", "id": "25"},
    )


def test_handle_delete_note_invalid():
    call_mcp_tool = MagicMock()

    result = handle_delete_note("メモ削除", "user123", call_mcp_tool)

    assert result == "削除するメモIDを指定してください。\n例: メモ削除25"
    call_mcp_tool.assert_not_called()


def test_handle_delete_note_no_match():
    call_mcp_tool = MagicMock()

    result = handle_delete_note("関係ないメッセージ", "user123", call_mcp_tool)

    assert result is None
    call_mcp_tool.assert_not_called()
