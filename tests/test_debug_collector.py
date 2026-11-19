from agents.debug.collector import collect_error


def test_collect_error_empty_text_returns_default_result():
    result = collect_error("")

    assert result["error_type"] is None
    assert result["file"] is None
    assert result["line"] is None
    assert result["message"] is None
    assert result["key"] is None
    assert result["raw"] == ""


def test_collect_error_none_text_returns_default_result():
    result = collect_error(None)

    assert result["error_type"] is None
    assert result["raw"] is None


def test_collect_error_key_error():
    text = """Traceback (most recent call last):
  File "app.py", line 120
KeyError: 'user_id'
"""
    result = collect_error(text)

    assert result["error_type"] == "KeyError"
    assert result["file"] == "app.py"
    assert result["line"] == 120
    assert result["message"] == "KeyError: 'user_id'"
    assert result["key"] == "user_id"


def test_collect_error_key_error_without_quotes():
    text = """File "handler.py", line 42
KeyError: user_id"""

    result = collect_error(text)

    assert result["error_type"] == "KeyError"
    assert result["key"] == "user_id"


def test_collect_error_type_error():
    text = """Traceback (most recent call last):
  File "service.py", line 88, in process
    total = value + None
TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'
"""
    result = collect_error(text)

    assert result["error_type"] == "TypeError"
    assert result["file"] == "service.py"
    assert result["line"] == 88
    assert result["message"] == (
        "TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'"
    )
    # TypeErrorはkey抽出の対象外
    assert result["key"] is None


def test_collect_error_value_error():
    text = """Traceback (most recent call last):
  File "parser.py", line 15, in parse_int
    return int(raw_value)
ValueError: invalid literal for int() with base 10: 'abc'
"""
    result = collect_error(text)

    assert result["error_type"] == "ValueError"
    assert result["file"] == "parser.py"
    assert result["line"] == 15
    assert result["key"] is None


def test_collect_error_attribute_error():
    text = """Traceback (most recent call last):
  File "models.py", line 33, in get_name
    return user.name
AttributeError: 'NoneType' object has no attribute 'name'
"""
    result = collect_error(text)

    assert result["error_type"] == "AttributeError"
    assert result["file"] == "models.py"
    assert result["line"] == 33
    assert result["key"] is None


def test_collect_error_name_error():
    text = """Traceback (most recent call last):
  File "main.py", line 7, in run
    print(undefined_variable)
NameError: name 'undefined_variable' is not defined
"""
    result = collect_error(text)

    assert result["error_type"] == "NameError"
    assert result["file"] == "main.py"
    assert result["line"] == 7
    assert result["key"] is None


def test_collect_error_generic_exception_type():
    text = """Traceback (most recent call last):
  File "worker.py", line 5
Exception: something went wrong
"""
    result = collect_error(text)

    assert result["error_type"] == "Exception"
    assert result["file"] == "worker.py"
    assert result["line"] == 5


def test_collect_error_no_match_returns_none_fields():
    text = "unrelated plain log line without traceback info"

    result = collect_error(text)

    assert result["error_type"] is None
    assert result["file"] is None
    assert result["line"] is None
    assert result["message"] == text
    assert result["raw"] == text


def test_collect_error_natural_language_extracts_file_hint():
    text = "app.pyのエラーを確認して"

    result = collect_error(text)

    assert result["file_hint"] == "app.py"
    assert result["error_type"] is None
    assert result["file"] is None
    assert result["line"] is None
    assert result["key"] is None


def test_collect_error_without_file_hint_keeps_file_hint_none():
    text = "エラーを確認して"

    result = collect_error(text)

    assert result["file_hint"] is None


def test_collect_error_traceback_still_extracts_existing_fields():
    text = """Traceback (most recent call last):
  File "app.py", line 120
KeyError: 'user_id'
"""

    result = collect_error(text)

    assert result["error_type"] == "KeyError"
    assert result["file"] == "app.py"
    assert result["line"] == 120
    assert result["key"] == "user_id"
    assert result["file_hint"] == "app.py"


def test_collect_error_prefers_render_traceback_over_user_message():
    result = collect_error(
        "app.pyのエラーを確認して",
        log_text='''Traceback (most recent call last):
  File "app.py", line 31, in start
ModuleNotFoundError: No module named 'linebot'\n''',
    )

    assert result["source"] == "render"
    assert result["error_type"] == "ModuleNotFoundError"
    assert result["file"] == "app.py"
    assert result["line"] == 31
    assert result["has_traceback"] is True


def test_collect_error_recognizes_exception_name_in_natural_language_only():
    result = collect_error("ModuleNotFoundErrorが発生しました。確認して")

    assert result["error_type"] == "ModuleNotFoundError"
    assert result["file"] is None
    assert result["line"] is None
    assert result["has_traceback"] is False


# --- 回帰テスト: "traceback"という単語だけでの誤判定を防ぐ ---


def test_collect_error_word_traceback_only_in_natural_language_is_not_traceback():
    """
    「さっきのtracebackの件」のように、実際のtraceback形式を伴わず
    "traceback"という単語だけを含む自然文はhas_traceback=Falseとなること。
    """
    result = collect_error("さっきのtracebackの件、直りましたか？")

    assert result["has_traceback"] is False
    assert result["source"] == "user_message"


def test_collect_error_word_traceback_only_in_render_log_is_not_traceback():
    """
    Renderログ本文に"traceback"という単語が含まれていても、
    実際のPython traceback形式(開始マーカー)がなければ
    has_traceback=Falseとなり、render_logsは解析対象として採用されないこと。
    """
    result = collect_error(
        "app.pyのエラーを確認して",
        log_text="INFO: traceback機能は現在利用できません",
    )

    assert result["has_traceback"] is False
    assert result["source"] == "user_message"


def test_collect_error_real_traceback_marker_is_still_detected():
    """
    Python標準のtraceback開始マーカーを含む場合は、
    これまで通りhas_traceback=Trueとなり、
    file / line / message が正しく取得できること。
    """
    text = """Traceback (most recent call last):
  File "app.py", line 120, in handler
KeyError: 'user_id'
"""

    result = collect_error(text)

    assert result["has_traceback"] is True
    assert result["error_type"] == "KeyError"
    assert result["file"] == "app.py"
    assert result["line"] == 120
    assert result["message"] == "KeyError: 'user_id'"


# --- 回帰テスト: traceback後の後続ログ行が抽出結果に混入しないこと ---


def test_collect_error_trailing_log_lines_do_not_leak_into_message():
    """
    Renderログでtracebackの後にDEBUG/INFOなどの後続ログ行が続いても、
    error_info["message"]にはtraceback内の例外サマリ行のみが入り、
    後続ログの内容(ここではテスト用のダミー文字列)が混入しないこと。
    """
    fake_render_log = (
        "2026-08-14T10:00:00 INFO service started\n"
        "2026-08-14T10:00:05 Traceback (most recent call last):\n"
        '  File "app.py", line 42, in handler\n'
        "KeyError: 'user_id'\n"
        "2026-08-14T10:00:06 DEBUG dummy_marker_should_not_leak\n"
    )

    result = collect_error(
        "app.pyのエラーを確認して",
        log_text=fake_render_log,
    )

    assert result["has_traceback"] is True
    assert result["error_type"] == "KeyError"
    assert result["file"] == "app.py"
    assert result["line"] == 42
    assert result["key"] == "user_id"
    assert result["message"] == "KeyError: 'user_id'"
    assert "dummy_marker_should_not_leak" not in result["message"]
    assert "dummy_marker_should_not_leak" not in str(result["file"])
    assert "dummy_marker_should_not_leak" not in str(result["key"])


def test_collect_error_trailing_log_lines_do_not_leak_into_key():
    """
    KeyErrorのキー抽出も、traceback後の後続ログ行の影響を受けないこと。
    """
    fake_render_log = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 10, in handler\n'
        "KeyError: 'user_id'\n"
        "DEBUG KeyError: 'unrelated_later_key'\n"
    )

    result = collect_error(
        "app.pyのエラーを確認して",
        log_text=fake_render_log,
    )

    assert result["key"] == "user_id"
    assert result["key"] != "unrelated_later_key"


# --- 回帰テスト: render_logsとrequest_text(自然文)の優先順序 ---


def test_collect_error_render_traceback_order_beats_request_text_exception_name():
    """
    request_text(ユーザー発言)に例外名らしき語が含まれていても、
    log_textに実際のtracebackがあれば、そちらのfile/lineが優先され、
    request_text側の情報で上書きされないこと。
    """
    result = collect_error(
        "TypeErrorが起きた気がするので確認して",
        log_text=(
            "Traceback (most recent call last):\n"
            '  File "worker.py", line 9, in run\n'
            "KeyError: 'job_id'\n"
        ),
    )

    assert result["source"] == "render"
    assert result["error_type"] == "KeyError"
    assert result["file"] == "worker.py"
    assert result["line"] == 9
    assert result["key"] == "job_id"


def test_collect_error_multiple_tracebacks_in_log_uses_first_block_only():
    """
    render_logsに複数のtracebackブロックが含まれる場合でも、
    file/line/message/keyは最初のtracebackブロックの内容から取得され、
    2つ目以降のブロックの内容が混入しないこと。
    """
    fake_render_log = (
        "Traceback (most recent call last):\n"
        '  File "first.py", line 1, in run\n'
        "KeyError: 'first_key'\n"
        "2026-08-14T10:00:06 DEBUG retry scheduled\n"
        "Traceback (most recent call last):\n"
        '  File "second.py", line 2, in run\n'
        "KeyError: 'second_key'\n"
    )

    result = collect_error(
        "app.pyのエラーを確認して",
        log_text=fake_render_log,
    )

    assert result["file"] == "first.py"
    assert result["line"] == 1
    assert result["key"] == "first_key"
    assert "second.py" not in str(result["file"])
    assert "second_key" != result["key"]
