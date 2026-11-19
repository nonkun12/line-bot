from agents.debug.analyzer import analyze_error


def _base_error_info(error_type):
    return {
        "error_type": error_type,
        "file": "app.py",
        "line": 42,
        "message": f"{error_type}: sample message",
    }


def test_analyze_error_key_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("KeyError"))

    assert "KeyError" in report
    assert "app.py" in report
    assert "42" in report
    assert "辞書型データに存在しないキーを参照しています" in report
    assert "get()による安全な取得" in report


def test_analyze_error_type_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("TypeError"))

    assert "TypeError" in report
    assert "型が一致していない可能性があります" in report
    assert "Noneチェック" in report


def test_analyze_error_value_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("ValueError"))

    assert "ValueError" in report
    assert "値の形式が期待値と異なる可能性があります" in report
    assert "変換処理確認" in report


def test_analyze_error_attribute_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("AttributeError"))

    assert "AttributeError" in report
    assert "オブジェクトに存在しない属性・メソッドを参照している可能性があります" in report
    assert "変数がNoneになっていないか確認" in report


def test_analyze_error_name_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("NameError"))

    assert "NameError" in report
    assert "定義されていない変数・関数を参照している可能性があります" in report
    assert "import漏れの確認" in report


def test_analyze_error_module_not_found_error_includes_dedicated_guidance():
    report = analyze_error(_base_error_info("ModuleNotFoundError"))

    assert "ModuleNotFoundError" in report
    assert "Pythonが指定されたモジュールを読み込めていません" in report
    assert "requirements.txtに必要なパッケージが含まれているか確認" in report


def test_analyze_error_unknown_error_type_falls_back_to_generic_guidance():
    report = analyze_error(_base_error_info("ZeroDivisionError"))

    assert "ZeroDivisionError" in report
    # KeyError/TypeError/ValueError/AttributeError/NameError以外は
    # 汎用メッセージにフォールバックする
    assert "ログ詳細を追加確認する必要があります" in report


def test_analyze_error_missing_fields_does_not_raise():
    report = analyze_error({})

    assert "None" in report
    assert "原因推測" in report
    assert "修正方針" in report


def test_analyze_error_always_appends_fix_policy_section():
    for error_type in ["KeyError", "TypeError", "ValueError", "AttributeError", "NameError"]:
        report = analyze_error(_base_error_info(error_type))
        assert "■ 修正方針" in report
        assert "原因箇所を確認し、安全な修正を行ってください。" in report


def test_analyze_error_with_file_hint_does_not_show_raw_none():
    report = analyze_error({
        "error_type": None,
        "file_hint": "app.py",
        "has_traceback": False,
    })

    assert "app.py" in report
    assert "■ 対象ファイル" in report
    assert "原因を特定できません" in report
    assert "■ エラー種類" not in report


def test_analyze_error_without_file_hint_keeps_generic_behavior():
    report = analyze_error({
        "error_type": None,
    })

    assert "■ エラー種類" in report
    assert "ログ詳細を追加確認する必要があります" in report


def test_analyze_error_without_traceback_does_not_claim_a_cause():
    report = analyze_error({
        "error_type": "ModuleNotFoundError",
        "file_hint": "app.py",
        "has_traceback": False,
        "log_fetch_error": "RENDER_API_KEY が設定されていません",
    })

    assert "原因を特定できません" in report
    assert "Renderログ取得失敗" in report
