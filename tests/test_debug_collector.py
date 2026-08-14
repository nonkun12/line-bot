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
