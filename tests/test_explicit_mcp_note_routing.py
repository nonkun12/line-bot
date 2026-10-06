from agents.notes.handlers import handle_natural_note_search
from agents.notes.intents import is_note_intent
from graph.supervisor import classify_intent


def test_explicit_mcp_note_search_is_notes_intent():
    message = "MCPでメモを検索し"
    assert is_note_intent(message)
    assert classify_intent(message) == "note"


def test_explicit_mcp_note_search_calls_search_notes_without_keyword():
    calls = []

    def fake_call(tool_name, arguments):
        calls.append((tool_name, arguments))
        return []

    result = handle_natural_note_search("MCPでメモを検索し", "user-1", fake_call)

    assert calls == [
        ("search_notes", {"user_id": "user-1", "keyword": ""}),
    ]
    assert result == []


def test_normal_chat_is_not_reclassified_as_mcp_note_search():
    assert not is_note_intent("MCPについて教えて")
