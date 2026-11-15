from __future__ import annotations

from types import SimpleNamespace

import app as app_module


def test_openclaw_prefixed_line_request_is_blocked_without_mac(monkeypatch):
    monkeypatch.setattr(
        app_module, "request_recovery_resume_review", lambda *_args, **_kwargs: (False, "")
    )
    monkeypatch.setattr(
        app_module, "request_distributed_loop", lambda *_args, **_kwargs: (False, "")
    )
    monkeypatch.setattr(app_module, "is_orchestrator_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda _message: None)
    monkeypatch.setattr(
        app_module, "enqueue_openclaw_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Mac queue must not be used")),
    )
    request = SimpleNamespace(
        message="OpenClaw: summarize the latest repository status",
        user_id="test-user",
        channel="line",
        metadata={},
    )
    reply = app_module._handle_ai_gateway_request(request)
    assert "旧OpenClaw Macブリッジは停止中" in reply
