from agents.debug.node import debug_agent_node


def test_debug_agent_node_natural_language_request():
    state = {
        "raw_message": "debug app.pyのエラーを確認して",
        "agent_results": {},
    }

    result = debug_agent_node(state)

    debug_result = result["agent_results"]["debug"]
    text = debug_result["text"]

    assert "app.py" in text
    assert "tracebackが見つか" in text
    assert "エラー種類\nNone" not in text
    assert "対象ファイル\nNone" not in text

    structured = debug_result["structured"]
    assert structured["error_info"]["file_hint"] == "app.py"
    assert structured["error_info"]["error_type"] is None


def test_debug_agent_node_real_traceback_still_works():
    state = {
        "raw_message": (
            "debug Traceback (most recent call last):\n"
            '  File "app.py", line 120\n'
            "KeyError: 'user_id'"
        ),
        "agent_results": {},
    }

    result = debug_agent_node(state)

    error_info = result["agent_results"]["debug"]["structured"]["error_info"]

    assert error_info["error_type"] == "KeyError"
    assert error_info["file"] == "app.py"
    assert error_info["line"] == 120
    assert error_info["key"] == "user_id"
