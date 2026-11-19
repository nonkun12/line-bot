from __future__ import annotations

from types import SimpleNamespace

import app as app_module


def test_openclaw_prefixed_line_request_uses_mac_queue(monkeypatch):
    """Explicit OpenClaw requests are queued for the Mac-local worker."""
    queued = []

    monkeypatch.setattr(
        app_module, "request_recovery_resume_review", lambda user_id, message: (False, "")
    )
    monkeypatch.setattr(
        app_module, "request_distributed_loop", lambda user_id, message: (False, "")
    )
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda message: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda message: None)
    monkeypatch.setattr(app_module, "enqueue_openclaw_request",
                        lambda user_id, message: queued.append((user_id, message)) or 23)
    monkeypatch.setattr(
        app_module, "run_core_request",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not use server AI")),
    )

    request = SimpleNamespace(
        message="OpenClaw: summarize the latest repository status",
        user_id="test-user",
        channel="line",
        metadata={},
    )
    reply = app_module._handle_ai_gateway_request(request)

    assert queued == [
        ("test-user", "OpenClaw: summarize the latest repository status")
    ]
    assert "Job 23" in reply
    assert "Bonsaiワーカー" in reply
