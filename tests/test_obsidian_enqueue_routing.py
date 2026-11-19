from types import SimpleNamespace

import app as line_app


def _request(message: str):
    return SimpleNamespace(message=message, user_id="test-user", channel="line", metadata={})


def test_explicit_obsidian_command_queues_and_returns_approval_message(monkeypatch):
    queued = []
    monkeypatch.setattr(line_app, "request_distributed_loop", lambda *_args: (False, ""))
    monkeypatch.setattr(
        line_app,
        "enqueue_obsidian_request",
        lambda user_id, message: queued.append((user_id, message)) or 123,
    )
    monkeypatch.setattr(
        line_app,
        "run_core_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explicit Obsidian requests must not fall through to cloud agent routing")
        ),
    )

    reply = line_app._handle_ai_gateway_request(_request("Obsidianに追記 LINE-Inbox.md: routing test"))

    assert queued == [("test-user", "Obsidianに追記 LINE-Inbox.md: routing test")]
    assert "Obsidianへの保存依頼を受け付けました" in reply
    assert "実行" in reply
    assert "123" in reply


def test_obsidian_queue_failure_fails_closed_without_fallback(monkeypatch):
    monkeypatch.setattr(line_app, "request_distributed_loop", lambda *_args: (False, ""))
    monkeypatch.setattr(
        line_app,
        "enqueue_obsidian_request",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("internal detail must not be returned")),
    )
    monkeypatch.setattr(
        line_app,
        "run_core_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failed queue request must not fall through to another handler")
        ),
    )

    reply = line_app._handle_ai_gateway_request(_request("Obsidianに追記 LINE-Inbox.md: routing test"))

    assert reply == "Obsidianへの保存依頼を受け付けられませんでした。設定を確認してください。"
    assert "internal detail" not in reply


def test_regular_message_does_not_enter_obsidian_queue(monkeypatch):
    queued = []
    monkeypatch.setattr(line_app, "request_distributed_loop", lambda *_args: (False, ""))
    monkeypatch.setattr(line_app, "enqueue_obsidian_request", lambda *args: queued.append(args))
    monkeypatch.setattr(line_app, "_core_dynamic_enabled", lambda: False)
    monkeypatch.setattr(line_app, "generate_reply", lambda _user, _message: "ordinary reply")

    reply = line_app._handle_ai_gateway_request(_request("こんにちは"))

    assert reply == "ordinary reply"
    assert queued == []
