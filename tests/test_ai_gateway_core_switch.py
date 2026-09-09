import app as app_module


def test_ai_gateway_defaults_to_legacy_path(monkeypatch):
    monkeypatch.delenv("AI_CORE_DYNAMIC_GRAPH", raising=False)
    monkeypatch.setattr(app_module, "generate_reply", lambda user_id, message: "legacy")

    response = app_module.app.ai_gateway.handle(
        app_module.app.ai_gateway._handler.__globals__["AIRequest"](
            user_id="u1", message="テスト", channel="line"
        )
    )

    assert response.text == "legacy"


def test_ai_gateway_uses_core_path_when_enabled(monkeypatch):
    monkeypatch.setenv("AI_CORE_DYNAMIC_GRAPH", "true")
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda user_id, message, call_mcp_tool=None: {
            "final_reply": "core",
        },
    )

    response = app_module.app.ai_gateway.handle(
        app_module.app.ai_gateway._handler.__globals__["AIRequest"](
            user_id="u1", message="テスト", channel="line"
        )
    )

    assert response.text == "core"


def test_ai_gateway_keeps_dashboard_command_on_legacy_path(monkeypatch):
    monkeypatch.setenv("AI_CORE_DYNAMIC_GRAPH", "true")
    monkeypatch.setattr(
        app_module,
        "generate_reply",
        lambda user_id, message: "dashboard",
    )
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not use Core")),
    )

    response = app_module.app.ai_gateway.handle(
        app_module.app.ai_gateway._handler.__globals__["AIRequest"](
            user_id="u1", message="ダッシュボード", channel="line"
        )
    )

    assert response.text == "dashboard"
