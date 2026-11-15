from types import SimpleNamespace

import app as line_app


def _request(message: str):
    return SimpleNamespace(message=message, user_id="test-user", channel="line", metadata={})


def test_explicit_obsidian_command_is_blocked_without_mac(monkeypatch):
    monkeypatch.setattr(line_app, "request_distributed_loop", lambda *_args, **_kwargs: (False, ""))
    monkeypatch.setattr(line_app, "request_recovery_resume_review", lambda *_args, **_kwargs: (False, ""))
    monkeypatch.setattr(line_app, "is_orchestrator_status_command", lambda _message: False)
    monkeypatch.setattr(line_app, "is_control_tower_status_command", lambda _message: False)
    monkeypatch.setattr(line_app, "handle_core_image_command", lambda _message: None)
    monkeypatch.setattr(
        line_app,
        "enqueue_obsidian_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Mac queue must not be used")),
    )
    reply = line_app._handle_ai_gateway_request(
        _request("Obsidianに追記 LINE-Inbox.md: routing test")
    )
    assert "旧Obsidian Macブリッジは停止中" in reply


def test_regular_message_does_not_enter_obsidian_queue(monkeypatch):
    queued = []
    monkeypatch.setattr(line_app, "request_distributed_loop", lambda *_args, **_kwargs: (False, ""))
    monkeypatch.setattr(line_app, "request_recovery_resume_review", lambda *_args, **_kwargs: (False, ""))
    monkeypatch.setattr(line_app, "is_orchestrator_status_command", lambda _message: False)
    monkeypatch.setattr(line_app, "is_control_tower_status_command", lambda _message: False)
    monkeypatch.setattr(line_app, "handle_core_image_command", lambda _message: None)
    monkeypatch.setattr(line_app, "enqueue_obsidian_request", lambda *args: queued.append(args))
    monkeypatch.setattr(line_app, "_core_dynamic_enabled", lambda: False)
    monkeypatch.setattr(line_app, "generate_reply", lambda _user, _message: "ordinary reply")
    reply = line_app._handle_ai_gateway_request(_request("こんにちは"))
    assert reply == "ordinary reply"
    assert queued == []
