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


def test_is_debug_intent_matches_python_exception_class_names():
    """
    回帰テスト: LINE実機で
    「app.pyでModuleNotFoundErrorが発生しました。確認して」が
    Debug Agentに届かなかった問題(is_debug_intentがFalseを返していた)
    の修正確認。

    日本語の「エラー」(カタカナ)を含まない、Pythonの例外クラス名
    (英字表記)のみのメッセージでもDebug Agentへ振り分けられること。
    """
    messages = [
        "app.pyでModuleNotFoundErrorが発生しました。確認して",
        "TypeErrorが出ました。確認して",
        "ValueErrorを調べて",
        "KeyErrorが発生しました。調査して",
        "AttributeErrorを確認して",
        "NameErrorが出た。確認して",
        "ImportErrorが発生しました。調べて",
    ]

    for message in messages:
        assert is_debug_intent(message) is True, message


def test_is_debug_intent_matches_unknown_python_exception_naming_pattern():
    """
    明示的なリストに含まれない例外名でも、"Xxxx" + "Error"/"Exception"
    という一般的な命名パターンであれば検出できることを確認する。
    """
    assert is_debug_intent("ZeroDivisionErrorが出た。確認して") is True
    assert is_debug_intent("CustomExceptionが発生しました。調べて") is True


def test_is_debug_intent_does_not_false_positive_on_bare_error_word():
    # 英単語"Error"単体(例外クラス名らしき接頭辞なし)では反応しない
    assert is_debug_intent("Errorが出た。確認して") is False


def test_is_debug_intent_python_exception_name_still_requires_investigate_word():
    # 例外クラス名があっても、調査依頼系キーワードが無ければ反応しない
    assert is_debug_intent("ModuleNotFoundErrorが発生しました") is False

def test_is_debug_intent_matches_file_and_natural_investigation_requests():
    """
    ファイル名 + 自然な調査依頼表現でもDebug Agentへ振り分ける。
    """
    messages = [
        "app.pyの原因を調べて",
        "app.pyの問題を確認して",
        "app.pyがおかしいので見て",
        "app.pyの問題を見て",
        "app.pyのエラー、原因わかる？",
        "app.pyのどこが悪いか調べて",
    ]

    for message in messages:
        assert is_debug_intent(message) is True, message


def test_is_debug_intent_does_not_false_positive_on_non_debug_file_requests():
    """
    ファイル名や「問題」だけではDebug Agentへ誤ルーティングしない。
    """
    messages = [
        "仕事の問題を調べて",
        "今日の予定を確認して",
        "READMEの問題を調べて",
    ]

    for message in messages:
        assert is_debug_intent(message) is False, message


def test_is_debug_intent_does_not_treat_general_python_file_questions_as_debug():
    """
    Pythonファイル名 + 「教えて」だけではDebugにしない。
    """
    messages = [
        "app.pyの書き方を教えて",
        "app.pyの使い方を教えて",
    ]

    for message in messages:
        assert is_debug_intent(message) is False, message
