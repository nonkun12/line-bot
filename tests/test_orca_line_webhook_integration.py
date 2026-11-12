"""Webhook-to-Orca intake integration tests using LINE's real signature verifier."""

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import app as app_module
import config as config_module
import db as db_module
import e2e_status as e2e_status_module


USER_ID = "U" + "a" * 32
MESSAGE_ID = "123456789012345678"


def _signed_body(secret, events):
    body = json.dumps(
        {
            "destination": "U" + "d" * 32,
            "events": events,
        },
        separators=(",", ":"),
    )
    signature = base64.b64encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode()
    return body, signature


def _text_event(text, *, user_id=USER_ID, message_id=MESSAGE_ID):
    source = {"type": "user", "userId": user_id} if user_id else {
        "type": "group", "groupId": "C" + "c" * 32,
    }
    return {
        "type": "message",
        "message": {"type": "text", "id": message_id, "text": text},
        "timestamp": 1794441600000,
        "source": source,
        "replyToken": "a" * 32,
        "mode": "active",
    }


def _prepare_handler(monkeypatch):
    app_module._processed_message_ids.clear()
    monkeypatch.setattr(db_module, "is_processed_event", lambda message_id: False)
    monkeypatch.setattr(
        db_module, "create_processed_event",
        lambda message_id, user_id=None, source=None: True,
    )
    monkeypatch.setattr(db_module, "delete_processed_event", lambda message_id: None)
    monkeypatch.setattr(e2e_status_module, "record_step", lambda *args, **kwargs: None)
    replies = []
    monkeypatch.setattr(app_module, "_line_push", lambda user_id, message: replies.append((user_id, message)))
    monkeypatch.setattr(config_module, "ORCA_TASK_API_URL", "https://orca.example.invalid")
    monkeypatch.setattr(config_module, "ORCA_TASK_API_TOKEN", "test-api-token")
    return replies


def test_signed_line_webhook_passes_verified_user_and_message_id_to_orca_intake(monkeypatch):
    replies = _prepare_handler(monkeypatch)
    requests = []

    def fake_post(url, *, json, headers, timeout):
        requests.append((url, json, headers, timeout))
        return SimpleNamespace(
            status_code=201,
            json=lambda: {
                "task": {"task_id": json["task_id"], "status": "queued"}
            },
        )

    monkeypatch.setattr(config_module.httpx, "post", fake_post)
    event = _text_event("タスク登録: アプリ開発: webhook integration")
    body, signature = _signed_body(config_module.CHANNEL_SECRET, [event])

    response = app_module.app.test_client().post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert len(requests) == 1
    url, payload, headers, timeout = requests[0]
    assert url == "https://orca.example.invalid"
    assert payload["request_text"] == "アプリ開発: webhook integration"
    assert payload["source_event_id"] == MESSAGE_ID
    assert payload["user_id"] == USER_ID
    assert payload["task_id"].startswith("line-")
    assert headers == {"Authorization": "Bearer test-api-token"}
    assert timeout == 8.0
    assert replies and replies[0][0] == USER_ID
    assert "受付しました" in replies[0][1]


def test_invalid_line_webhook_signature_is_rejected_before_orca_intake(monkeypatch):
    _prepare_handler(monkeypatch)
    calls = []
    monkeypatch.setattr(
        config_module.httpx, "post",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    event = _text_event("タスク登録: アプリ開発: should not register")
    body, _ = _signed_body(config_module.CHANNEL_SECRET, [event])

    response = app_module.app.test_client().post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": "invalid-signature", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid signature"
    assert calls == []


def test_signed_group_webhook_without_line_user_id_fails_closed(monkeypatch):
    _prepare_handler(monkeypatch)
    calls = []
    monkeypatch.setattr(
        config_module.httpx, "post",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    event = _text_event(
        "タスク登録: アプリ開発: ownerless request",
        user_id=None,
        message_id="123456789012345679",
    )
    body, signature = _signed_body(config_module.CHANNEL_SECRET, [event])

    response = app_module.app.test_client().post(
        "/callback",
        data=body,
        headers={"X-Line-Signature": signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert calls == []
