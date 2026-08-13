"""
Supervisor's natural-language Debug Agent routing.

「debug」プレフィックスなしの自然文(例: 「app.pyのエラーを確認して」)が
Debug Agentへ正しくルーティングされること、かつGitHub/Sheets/Notes/Memory
等の既存Agentへの誤ルーティングを引き起こさないことを確認する回帰テスト。
"""

from agents.debug.node import debug_agent_node
from graph.supervisor import classify_intent


def test_classify_intent_routes_natural_language_debug_requests_to_debug():
    messages = [
        "app.pyのエラーを確認して",
        "app.pyのエラーを調べて",
        "このエラーを確認して",
        "エラーを調査して",
    ]

    for message in messages:
        assert classify_intent(message) == "debug"


def test_classify_intent_still_prioritizes_debug_prefix():
    assert classify_intent("debug something broke") == "debug"
    assert classify_intent("debug app.pyのエラーを確認して") == "debug"


def test_classify_intent_does_not_misroute_schedule_to_debug():
    assert classify_intent("予定を確認して") != "debug"


def test_classify_intent_does_not_misroute_sheets_to_debug():
    assert classify_intent("シートを確認して") == "sheets"
    assert classify_intent("Google Sheetsを確認したい") == "sheets"


def test_classify_intent_does_not_misroute_github_to_debug():
    assert classify_intent("Issueを確認して") == "github"
    assert classify_intent("GitHubのコミットを確認して") == "github"


def test_classify_intent_unrelated_messages_still_unsupported():
    assert classify_intent("今日は天気がいいですね") == "unsupported"


def test_classify_intent_routes_python_exception_name_messages_to_debug():
    """
    回帰テスト: LINE実機バグ修正確認。
    「app.pyでModuleNotFoundErrorが発生しました。確認して」のような、
    日本語の「エラー」を含まずPython例外クラス名(英字表記)のみを
    含む自然文でも、Debug Agentへルーティングされること。
    """
    messages = [
        "app.pyでModuleNotFoundErrorが発生しました。確認して",
        "TypeErrorが出ました。確認して",
        "KeyErrorが発生しました。調査して",
    ]

    for message in messages:
        assert classify_intent(message) == "debug"


def test_debug_agent_node_reached_via_natural_language_without_prefix():
    """
    エンドツーエンド回帰テスト:
    「debug」プレフィックスなしの自然文でもDebug Agentまで到達し、
    かつ「エラー種類: None」のような壊れた出力にならないこと。
    """
    raw_message = "app.pyのエラーを確認して"

    intent = classify_intent(raw_message)
    assert intent == "debug"

    state = {
        "raw_message": raw_message,
        "agent_results": {},
    }

    result = debug_agent_node(state)
    text = result["agent_results"]["debug"]["text"]

    assert "app.py" in text
    assert "tracebackが見つか" in text
    assert "エラー種類\nNone" not in text


def test_debug_agent_node_reached_via_python_exception_name_without_prefix():
    """
    エンドツーエンド回帰テスト:
    「app.pyでModuleNotFoundErrorが発生しました。確認して」のような、
    Python例外クラス名を含む自然文でもDebug Agentまで到達すること。
    """
    raw_message = "app.pyでModuleNotFoundErrorが発生しました。確認して"

    intent = classify_intent(raw_message)
    assert intent == "debug"

    state = {
        "raw_message": raw_message,
        "agent_results": {},
    }

    result = debug_agent_node(state)
    text = result["agent_results"]["debug"]["text"]

    assert "app.py" in text
