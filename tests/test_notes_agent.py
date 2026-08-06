from unittest.mock import MagicMock, patch

from agents.notes.intents import is_note_intent
from agents.notes.node import notes_agent_node
from graph.graph import graph


def test_is_note_intent_recognizes_notes_commands():
    assert is_note_intent("メモ一覧")
    assert is_note_intent("メモ検索 テニス")
    assert is_note_intent("メモして 予約")
    assert is_note_intent("5番のメモを削除して")
    assert is_note_intent("メモ削除10")
    assert is_note_intent("メモを全部削除して")
    assert is_note_intent("LINE Botのメモを探して")
    assert is_note_intent("明日旅行する予定")


def test_notes_agent_node_save_note_calls_save_note():
    call_mcp_tool = MagicMock(return_value="saved")

    result = notes_agent_node(
        {
            "user_id": "user123",
            "raw_message": "メモして 予約",
            "call_mcp_tool": call_mcp_tool,
        }
    )

    assert result["agent_results"]["notes"]["text"] == "saved"
    call_mcp_tool.assert_called_once_with(
        "save_note",
        {
            "user_id": "user123",
            "title": "LINEメモ",
            "body": "予約",
            "category": "予定",
        },
    )


def test_notes_agent_node_list_calls_search_notes():
    call_mcp_tool = MagicMock(return_value="list result")

    result = notes_agent_node(
        {
            "user_id": "user123",
            "raw_message": "メモ一覧",
            "call_mcp_tool": call_mcp_tool,
        }
    )

    assert result["agent_results"]["notes"]["text"] == "list result"
    call_mcp_tool.assert_called_once_with(
        "search_notes",
        {
            "user_id": "user123",
            "keyword": "",
        },
    )


def test_notes_graph_routes_note_intent_to_notes_agent():
    with patch("mcp_client.call_mcp_tool", return_value="list result") as mock_call:
        result = graph.invoke(
            {
                "user_id": "test-user",
                "raw_message": "メモ一覧",
                "agent_results": {},
            }
        )

    assert result is not None
    assert result.get("agent_results", {}).get("notes", {}).get("text") == "list result"
    assert "Notes" in result.get("final_reply", "")
    mock_call.assert_called_once_with("search_notes", {"user_id": "test-user", "keyword": ""})
