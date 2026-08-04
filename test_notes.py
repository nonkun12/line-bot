from unittest.mock import MagicMock
from notes import (
    handle_list_notes,
    handle_search_notes,
    handle_natural_note_search,
    handle_save_note,
    handle_auto_save_note,
    handle_delete_note,
)


def test_handle_list_notes():
    call_mcp_tool = MagicMock(return_value="mocked notes list")
    result = handle_list_notes("user123", call_mcp_tool)

    assert result == "mocked notes list"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "",
        },
    )


def test_handle_search_notes_success():
    call_mcp_tool = MagicMock(return_value="search results")
    result = handle_search_notes("メモ検索 テニス", "user123", call_mcp_tool)

    assert result == "search results"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "テニス",
        },
    )


def test_handle_search_notes_no_keyword():
    call_mcp_tool = MagicMock()
    result = handle_search_notes("メモ検索", "user123", call_mcp_tool)

    assert "検索キーワードを指定してください" in result
    call_mcp_tool.assert_not_called()


def test_handle_search_notes_no_keyword_spaces():
    call_mcp_tool = MagicMock()
    result = handle_search_notes("メモ検索  ", "user123", call_mcp_tool)

    assert "検索キーワードを指定してください" in result
    call_mcp_tool.assert_not_called()


def test_handle_natural_note_search_with_exact_phrase():
    call_mcp_tool = MagicMock(return_value="natural search results")
    result = handle_natural_note_search("LINE Botのメモを探して", "user123", call_mcp_tool)
    assert result == "natural search results"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "",
        },
    )


def test_handle_natural_note_search_keyword_extraction():
    call_mcp_tool = MagicMock(return_value="natural search results")
    result = handle_natural_note_search("テニスのメモを探して", "user123", call_mcp_tool)

    assert result == "natural search results"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "テニスの",
        },
    )


def test_handle_natural_note_search_my_notes():
    call_mcp_tool = MagicMock(return_value="my notes")
    result = handle_natural_note_search("私のメモ", "user123", call_mcp_tool)

    assert result == "my notes"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "",
        },
    )


def test_handle_auto_save_note_success():
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


def test_handle_auto_save_note_exclude_keyword():
    call_mcp_tool = MagicMock()
    result = handle_auto_save_note("予定ある？", "user123", call_mcp_tool)

    assert result is None
    call_mcp_tool.assert_not_called()


def test_handle_auto_save_note_short_message():
    call_mcp_tool = MagicMock()
    result = handle_auto_save_note("予定する", "user123", call_mcp_tool)

    assert result is None
    call_mcp_tool.assert_not_called()


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
        {
            "user_id": "user123",
            "id": "5",
        },
    )


def test_handle_delete_note_explicit():
    call_mcp_tool = MagicMock(return_value="deleted")
    result = handle_delete_note("メモ削除10", "user123", call_mcp_tool)

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_note",
        {
            "user_id": "user123",
            "id": "10",
        },
    )


def test_handle_delete_note_explicit_zenkaku():
    call_mcp_tool = MagicMock(return_value="deleted")
    result = handle_delete_note("メモ削除２５", "user123", call_mcp_tool)

    assert result == "deleted"
    call_mcp_tool.assert_called_once_with(
        "delete_note",
        {
            "user_id": "user123",
            "id": "25",
        },
    )


def test_handle_delete_note_explicit_no_id():
    call_mcp_tool = MagicMock()
    result = handle_delete_note("メモ削除", "user123", call_mcp_tool)

    assert "削除するメモIDを指定してください" in result
    call_mcp_tool.assert_not_called()


def test_handle_delete_note_no_match():
    call_mcp_tool = MagicMock()
    result = handle_delete_note("関係ないメッセージ", "user123", call_mcp_tool)

    assert result is None
    call_mcp_tool.assert_not_called()
