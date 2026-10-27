from __future__ import annotations

from types import SimpleNamespace

import app as app_module


def test_openclaw_prefixed_line_request_uses_server_ai(monkeypatch):
    """Legacy OpenClaw prefix must not enqueue work for a Mac-local worker."""
    seen = {}

    monkeypatch.setattr(
        app_module, "request_recovery_resume_review", lambda user_id, message: (False, "")
    )
    monkeypatch.setattr(
        app_module, "request_distributed_loop", lambda user_id, message: (False, "")
    )
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda message: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda message: None)
    monkeypatch.setattr(app_module, "is_obsidian_intent", lambda message: False)
    monkeypatch.setattr(app_module, "extract_app_development_request", lambda message: None)
    monkeypatch.setattr(app_module, "handle_self_introduction", lambda message: None)
    monkeypatch.setattr(app_module, "extract_development_instruction", lambda message: None)
    monkeypatch.setattr(app_module, "_core_dynamic_enabled", lambda: True)
    monkeypatch.setattr(app_module, "should_route_to_management_ai", lambda message: False)

    def fake_run_core_request(user_id, message, **kwargs):
        seen["message"] = message
        return "server-side-result"

    monkeypatch.setattr(app_module, "run_core_request", fake_run_core_request)
    monkeypatch.setattr(app_module, "extract_core_reply", lambda result: result)

    request = SimpleNamespace(
        message="OpenClaw: summarize the latest repository status",
        user_id="test-user",
        channel="line",
        metadata={},
    )
    reply = app_module._handle_ai_gateway_request(request)

    assert reply == "server-side-result"
    assert seen["message"] == "summarize the latest repository status"
