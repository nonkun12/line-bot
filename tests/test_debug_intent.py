from agents.debug.intents import is_debug_intent


def test_is_debug_intent_matches_natural_language_error_requests():
    messages = [
        "app.pyのエラーを確認して",
        "app.pyのエラーを調べて",
        "このエラーを確認して",
        "エラーを調査して",
        "バグを調べてほしい",
    ]

    for message in messages:
        assert is_debug_intent(message) is True


def test_is_debug_intent_false_without_error_keyword():
    # 「確認して」等の調査依頼系キーワードだけでは反応しない
    assert is_debug_intent("予定を確認して") is False
    assert is_debug_intent("シートを確認して") is False
    assert is_debug_intent("READMEの書き方を教えて") is False


def test_is_debug_intent_false_without_investigate_keyword():
    # エラー系キーワードだけでは反応しない(雑談との混同防止)
    assert is_debug_intent("今日は最悪な一日だった") is False


def test_is_debug_intent_false_for_empty():
    assert is_debug_intent("") is False
    assert is_debug_intent(None) is False


def test_is_debug_intent_true_with_debug_prefix_message_too():
    # 「debug」プレフィックス付きメッセージに対しても
    # (Supervisor側では別ロジックで先に捕捉されるが)
    # 関数単体としては矛盾なくTrueを返すことを確認する
    assert is_debug_intent("debug app.pyのエラーを確認して") is True
