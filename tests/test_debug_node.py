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


def test_debug_agent_node_word_traceback_only_does_not_reach_fix_ready_state(monkeypatch):
    """
    「traceback」という単語だけを含む自然文(実際のtraceback形式なし)では、
    has_traceback=Falseとなり、Fix経路へ進める状態にならないこと。
    """
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: "INFO service started successfully",
    )

    result = debug_agent_node({
        "raw_message": "さっきのtracebackの件、直りましたか？",
        "agent_results": {},
    })

    structured = result["agent_results"]["debug"]["structured"]
    assert structured["error_info"]["has_traceback"] is False


def test_debug_agent_node_trailing_render_log_does_not_leak_into_agent_results_or_reply(monkeypatch):
    """
    traceback後に続くDEBUG/INFOログ行(機密情報を模したダミー文字列)が、
    agent_results(state)にもLINE返信本文にも混入しないこと。

    ダミー文字列は実際の秘密情報ではなく、混入検知用のマーカー文字列。
    """
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: (
            "2026-08-14T10:00:00 INFO service started\n"
            "2026-08-14T10:00:05 Traceback (most recent call last):\n"
            '  File "app.py", line 42, in handler\n'
            "KeyError: 'user_id'\n"
            "2026-08-14T10:00:06 DEBUG dummy_marker_should_not_leak\n"
        ),
    )

    result = debug_agent_node({
        "raw_message": "app.pyのエラーを確認して",
        "agent_results": {},
    })

    debug_result = result["agent_results"]["debug"]
    structured = debug_result["structured"]

    assert structured["error_info"]["message"] == "KeyError: 'user_id'"
    assert "dummy_marker_should_not_leak" not in repr(result["agent_results"])
    assert "dummy_marker_should_not_leak" not in debug_result["text"]
