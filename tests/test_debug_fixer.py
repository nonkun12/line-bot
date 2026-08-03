from agents.debug.fixer import generate_fix_suggestion


def _base_error_info(error_type):
    return {
        "error_type": error_type,
        "file": "app.py",
        "line": 42,
        "message": f"{error_type}: sample message",
    }


def test_generate_fix_suggestion_key_error_includes_example_patch():
    result = generate_fix_suggestion(_base_error_info("KeyError"))

    assert "KeyError" in result
    assert "app.py" in result
    assert "42" in result
    assert 'data["user_id"]' in result
    assert "data.get(\"user_id\")" in result


def test_generate_fix_suggestion_type_error_includes_type_check_advice():
    result = generate_fix_suggestion(_base_error_info("TypeError"))

    assert "TypeError" in result
    assert "型チェックを追加" in result
    assert "Noneチェックを追加" in result


def test_generate_fix_suggestion_value_error_includes_validation_advice():
    result = generate_fix_suggestion(_base_error_info("ValueError"))

    assert "ValueError" in result
    assert "入力値検証を追加" in result
    assert "変換処理を確認" in result


def test_generate_fix_suggestion_attribute_error_includes_dedicated_advice():
    result = generate_fix_suggestion(_base_error_info("AttributeError"))

    assert "AttributeError" in result
    assert "呼び出し前にNoneチェックを追加" in result
    assert "hasattr()による安全な属性確認を追加" in result


def test_generate_fix_suggestion_name_error_includes_dedicated_advice():
    result = generate_fix_suggestion(_base_error_info("NameError"))

    assert "NameError" in result
    assert "変数名・関数名のスペルを確認" in result
    assert "必要なimport文を追加" in result


def test_generate_fix_suggestion_unknown_error_type_falls_back_to_generic_advice():
    result = generate_fix_suggestion(_base_error_info("ZeroDivisionError"))

    assert "ZeroDivisionError" in result
    # KeyError/TypeError/ValueError/AttributeError/NameError以外は
    # 汎用メッセージにフォールバックする
    assert "詳細ログを確認して修正箇所を特定してください。" in result


def test_generate_fix_suggestion_missing_fields_does_not_raise():
    result = generate_fix_suggestion({})

    assert "None" in result
    assert "■ 修正案" in result


def test_generate_fix_suggestion_always_includes_header_sections():
    for error_type in ["KeyError", "TypeError", "ValueError", "AttributeError", "NameError"]:
        result = generate_fix_suggestion(_base_error_info(error_type))
        assert "■ 対象ファイル" in result
        assert "■ 行番号" in result
        assert "■ 修正案" in result
