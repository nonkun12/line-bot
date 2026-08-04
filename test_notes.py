from unittest.mock import MagicMock
from notes import (
    handle_list_notes,
    handle_search_notes,
    handle_natural_note_search,
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
    # キーワードが空（またはスペースのみ）の場合は、エラーメッセージを返しMCPツールを呼ばない
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
