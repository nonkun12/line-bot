"""
Sheets Agent intent classification.

Verifies that natural-language questions about Google Sheets content
(e.g. "シートの内容を分析して") are routed to the Sheets Agent via
Supervisor -> Router -> sheets_agent, not just the previously supported
fixed phrases (記録/追加/見て/読んで/検索/削除).
"""

from agents.sheets.intents import is_sheets_intent
from graph.supervisor import classify_intent, supervisor_node


def test_is_sheets_intent_still_matches_existing_fixed_phrases():
    messages = [
        "シートに記録して",
        "シートに追加して",
        "シートを見て",
        "シートを読んで",
        "シートから検索 Amazon",
        "シートを検索",
        "シートからAmazon打合せを削除して",
        "Google Sheetsを確認したい",
    ]

    for message in messages:
        assert is_sheets_intent(message) is True


def test_is_sheets_intent_matches_natural_language_analysis_requests():
    messages = [
        "シートの内容を見て、重要な予定を教えて",
        "シートの内容を分析して",
        "シートの中から重要な予定を教えて",
        "Amazon打合せについてシートに何が書いてある？",
        "このシートの内容を簡単にまとめて",
    ]

    for message in messages:
        assert is_sheets_intent(message) is True


def test_is_sheets_intent_returns_false_for_unrelated_messages():
    assert is_sheets_intent("今日は天気がいいですね") is False
    assert is_sheets_intent("") is False
    assert is_sheets_intent(None) is False


def test_classify_intent_routes_natural_language_sheets_questions_to_sheets():
    messages = [
        "シートの内容を分析して",
        "シートから重要な予定を教えて",
        "このシートの内容を簡単にまとめて",
    ]

    for message in messages:
        assert classify_intent(message) == "sheets"


def test_supervisor_node_sets_next_agent_to_sheets_for_analysis_request():
    state = {
        "user_id": "user123",
        "raw_message": "シートの内容を分析して",
    }

    result = supervisor_node(state)

    assert result["intent"] == "sheets"
    assert result["next_agent"] == "sheets"


def test_classify_intent_routes_sheets_before_note_and_memory_generic_keywords():
    """
    回帰テスト: Supervisorの判定順序バグ。

    「シートに記録 明日の予定」のようなSheets向けメッセージが、
    Notes/Memory Agentの汎用キーワード判定(「予定」「したい」「名前」等)に
    先に捕捉され、誤って note/memory へルーティングされていた問題を防ぐ。
    """
    messages = [
        "シートに記録 明日の予定",
        "シートに名前を記録して",
        "シートに私の予定を記録して",
        "シートに記録したい予定がある",
    ]

    for message in messages:
        assert classify_intent(message) == "sheets"
