from agents.debug.node import debug_agent_node


def test_debug_agent_node_uses_render_traceback_for_natural_language_request(monkeypatch):
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: '''SECRET_RENDER_VALUE=do-not-store
Traceback (most recent call last):
  File "app.py", line 12, in <module>
ModuleNotFoundError: No module named 'missing_package'\n''',
    )

    state = {
        "raw_message": "app.pyのエラーを確認して",
        "agent_results": {},
    }

    result = debug_agent_node(state)

    debug_result = result["agent_results"]["debug"]
    text = debug_result["text"]

    assert "app.py" in text
    assert "ModuleNotFoundError" in text

    structured = debug_result["structured"]
    assert structured["error_info"]["file_hint"] == "app.py"
    assert structured["error_info"]["error_type"] == "ModuleNotFoundError"
    assert structured["error_info"]["file"] == "app.py"
    assert structured["error_info"]["line"] == 12
    assert structured["error_info"]["has_traceback"] is True
    assert "raw" not in structured["error_info"]
    assert "request_text" not in structured["error_info"]
    assert "SECRET_RENDER_VALUE" not in repr(result["agent_results"])
    assert structured["log_source"] == "render"
    assert structured["log_fetch_error"] is None


def test_debug_agent_node_real_traceback_still_works_when_render_fetch_fails(monkeypatch):
    def raise_render_error():
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("agents.debug.node.get_render_logs", raise_render_error)

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
    assert error_info["source"] == "user_message"
    assert "Renderログ取得に失敗しました" in error_info["log_fetch_error"]


def test_debug_agent_node_handles_missing_render_api_key_without_parsing_it(monkeypatch):
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: "RENDER_API_KEY が設定されていません",
    )

    result = debug_agent_node({
        "raw_message": "app.pyのエラーを確認して",
        "agent_results": {},
    })

    structured = result["agent_results"]["debug"]["structured"]
    error_info = structured["error_info"]

    assert error_info["error_type"] is None
    assert "raw" not in error_info
    assert "request_text" not in error_info
    assert structured["log_source"] == "user_message"
    assert structured["log_fetch_error"] == "RENDER_API_KEY が設定されていません"
    assert "原因を特定できません" in result["agent_results"]["debug"]["text"]


def test_debug_agent_node_marks_missing_traceback_as_unknown(monkeypatch):
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: "INFO service started successfully",
    )

    result = debug_agent_node({
        "raw_message": "app.pyのエラーを確認して",
        "agent_results": {},
    })

    debug_result = result["agent_results"]["debug"]
    assert debug_result["structured"]["log_fetch_error"] is None
    assert "原因を特定できません" in debug_result["text"]
