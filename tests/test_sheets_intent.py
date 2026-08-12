"""
Sheets Agent intent classification.

Verifies that natural-language questions about Google Sheets content
(e.g. "シートの内容を分析して") are routed to the Sheets Agent via
Supervisor -> Router -> sheets_agent, not just the previously supported
fixed phrases (記録/追加/見て/読んで/検索/削除).
"""

from unittest.mock import MagicMock, patch

from agents.sheets.intents import is_sheets_intent
from agents.sheets.handlers import handle_sheets_message
from agents.sheets.node import sheets_agent_node
from graph.supervisor import classify_intent, supervisor_node
from graph.router import route_from_supervisor


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


def test_classify_intent_routes_natural_language_read_questions_to_sheets():
    """
    「シートの内容は？」のような自然な読み取りの言い方も、
    Supervisorの段階でSheets Agentへ正しくルーティングされること。
    """
    messages = [
        "シートの内容は？",
        "シートの中身を見せて",
        "シートを確認して",
        "シートのデータを見せて",
        "Google Sheetsの内容を見せて",
        "Google Sheetsを確認して",
        "シートには何が入ってる？",
        "シートに何が記録されている？",
    ]

    for message in messages:
        assert classify_intent(message) == "sheets"


def test_sheets_agent_node_routes_natural_read_question_to_existing_read_handler():
    """
    エンドツーエンドの回帰テスト:
    Supervisor -> Router -> sheets_agent_node の一連の流れで、
    「シートの内容は？」が「Google Sheetsの操作を理解できませんでした。」
    にならず、既存のRead処理(生データの一覧表示)の結果を返すこと。
    """
    state = {
        "user_id": "user123",
        "raw_message": "シートの内容は？",
    }

    supervised_state = supervisor_node(state)

    assert supervised_state["intent"] == "sheets"
    assert supervised_state["next_agent"] == "sheets"
    assert route_from_supervisor(supervised_state) == "sheets_agent"

    fake_client = MagicMock()
    fake_client.read_rows.return_value = [["テスト1"], ["テスト2"]]

    with patch(
        "agents.sheets.node.GoogleSheetsClient",
        return_value=fake_client,
    ):
        result_state = sheets_agent_node(supervised_state)

    sheets_result = result_state["agent_results"]["sheets"]

    assert sheets_result["success"] is True
    assert sheets_result["text"] != "Google Sheetsの操作を理解できませんでした。"
    assert sheets_result["text"].startswith("Google Sheetsの内容：")
    fake_client.read_rows.assert_called_once_with("A:Z")


def test_sheets_agent_node_write_and_read_still_work_end_to_end():
    """
    今回の修正後も、既存の書き込み・読み取り(固定フレーズ)が
    Supervisor -> Router -> sheets_agent_node のend-to-endで
    引き続き正常に動作することを確認する回帰テスト。
    """
    # 書き込み: 「シートにテスト1を記録」
    write_state = {
        "user_id": "user123",
        "raw_message": "シートにテスト1を記録",
    }
    supervised_write_state = supervisor_node(write_state)
    assert supervised_write_state["next_agent"] == "sheets"

    write_client = MagicMock()

    with patch(
        "agents.sheets.node.GoogleSheetsClient",
        return_value=write_client,
    ):
        write_result_state = sheets_agent_node(supervised_write_state)

    write_result = write_result_state["agent_results"]["sheets"]
    assert write_result["success"] is True
    assert write_result["text"] == "Google Sheetsに記録しました：テスト1"
    write_client.append_row.assert_called_once_with("A:A", ["テスト1"])

    # 読み取り: 「シートを読んで」
    read_state = {
        "user_id": "user123",
        "raw_message": "シートを読んで",
    }
    supervised_read_state = supervisor_node(read_state)
    assert supervised_read_state["next_agent"] == "sheets"

    read_client = MagicMock()
    read_client.read_rows.return_value = [["テスト1"]]

    with patch(
        "agents.sheets.node.GoogleSheetsClient",
        return_value=read_client,
    ):
        read_result_state = sheets_agent_node(supervised_read_state)

    read_result = read_result_state["agent_results"]["sheets"]
    assert read_result["success"] is True
    assert read_result["text"].startswith("Google Sheetsの内容：")


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
