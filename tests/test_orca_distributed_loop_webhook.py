"""Signed LINE webhook integration for typed distributed-loop D1 intake."""
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


def _signed_body(events):
    body = json.dumps({"destination": "U" + "d" * 32, "events": events}, separators=(",", ":"))
    signature = base64.b64encode(
        hmac.new(config_module.CHANNEL_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    ).decode()
    return body, signature


def _event(text, message_id=MESSAGE_ID, user_id=USER_ID):
    source = {"type": "user", "userId": user_id} if user_id else {
        "type": "group", "groupId": "C" + "c" * 32,
    }
    return {
        "type": "message",
        "message": {"type": "text", "id": message_id, "text": text, "quoteToken": "quote-token-123"},
        "timestamp": 1794441600000,
        "webhookEventId": "01JCM000000000000000000000",
        "deliveryContext": {"isRedelivery": False},
        "source": source,
        "replyToken": "a" * 32,
        "mode": "active",
    }


def _prepare(monkeypatch):
    app_module._processed_message_ids.clear()
    monkeypatch.setattr(db_module, "is_processed_event", lambda _id: False)
    monkeypatch.setattr(db_module, "create_processed_event", lambda *_a, **_k: True)
    monkeypatch.setattr(db_module, "delete_processed_event", lambda _id: None)
    monkeypatch.setattr(e2e_status_module, "record_step", lambda *_a, **_k: None)
    monkeypatch.setattr(app_module, "record_step", lambda *_a, **_k: None)
    replies = []
    monkeypatch.setattr(app_module, "_line_push", lambda user, msg: replies.append((user, msg)))
    monkeypatch.setattr(config_module, "ORCA_TASK_API_URL", "https://orca.example.invalid")
    monkeypatch.setattr(config_module, "ORCA_TASK_API_TOKEN", "test-api-token")
    monkeypatch.setattr(config_module, "ORCA_TASK_APPROVAL_HMAC_KEY", "k" * 40)
    return replies


def _post(client, text, message_id=MESSAGE_ID):
    body, signature = _signed_body([_event(text, message_id)])
    return client.post("/callback", data=body, headers={
        "X-Line-Signature": signature, "Content-Type": "application/json",
    })


def test_signed_webhook_registers_typed_loop_without_dispatch(monkeypatch):
    replies = _prepare(monkeypatch)
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        return SimpleNamespace(status_code=201, json=lambda: {"task": {
            "task_id": json["task_id"], "task_type": json["task_type"],
            "max_tasks": json["max_tasks"], "status": "queued",
        }})

    monkeypatch.setattr(config_module.httpx, "post", fake_post)
    response = _post(app_module.app.test_client(),
                     "分散Loop登録: 分散Loopを4回、安全確認付きで実行")
    assert response.status_code == 200
    assert len(calls) == 1
    _, payload, headers, timeout = calls[0]
    assert payload["task_type"] == "distributed_loop"
    assert payload["max_tasks"] == 4
    assert payload["request_text"] == "分散Loopを4回、安全確認付きで実行"
    assert payload["source_event_id"] == MESSAGE_ID
    assert payload["user_id"] == USER_ID
    assert headers == {"Authorization": "Bearer test-api-token"}
    assert timeout == 8.0
    assert replies and "まだ実行されません" in replies[0][1]
    assert "Task ID:" in replies[0][1]


def test_signed_webhook_approves_loop_with_protocol_v2(monkeypatch):
    replies = _prepare(monkeypatch)
    task_id = "line-loop-test123"
    command = "分散Loopを2回、安全確認付きで実行"
    calls = []

    def fake_get(url, *, headers, timeout):
        calls.append(("get", url, headers, timeout))
        return SimpleNamespace(status_code=200, json=lambda: {"task": {
            "task_id": task_id, "request_text": command, "status": "queued",
            "task_type": "distributed_loop", "max_tasks": 2,
        }})

    def fake_post(url, *, json, headers, timeout):
        calls.append(("post", url, json, headers, timeout))
        return SimpleNamespace(status_code=200, json=lambda: {
            "approved": True, "expires_at": json["expires_at"],
        })

    monkeypatch.setattr(config_module.httpx, "get", fake_get)
    monkeypatch.setattr(config_module.httpx, "post", fake_post)
    response = _post(app_module.app.test_client(), f"分散Loop承認: {task_id}")
    assert response.status_code == 200
    approval = next(call[2] for call in calls if call[0] == "post")
    assert approval["task_type"] == "distributed_loop"
    assert approval["max_tasks"] == 2
    assert approval["approver_user_id"] == USER_ID
    assert len(approval["nonce"]) == 32
    assert len(approval["signature"]) == 64
    assert replies and "まだ実行されません" in replies[0][1]


def test_invalid_signature_and_group_owner_fail_closed(monkeypatch):
    _prepare(monkeypatch)
    calls = []
    monkeypatch.setattr(config_module.httpx, "post", lambda *a, **k: calls.append((a, k)))
    client = app_module.app.test_client()
    body, _signature = _signed_body([_event("分散Loop登録: 分散Loop開始")])
    invalid = client.post("/callback", data=body, headers={
        "X-Line-Signature": "invalid", "Content-Type": "application/json",
    })
    assert invalid.status_code == 400
    group = _event("分散Loop登録: 分散Loop開始", message_id="123456789012345679", user_id=None)
    body, signature = _signed_body([group])
    ownerless = client.post("/callback", data=body, headers={
        "X-Line-Signature": signature, "Content-Type": "application/json",
    })
    assert ownerless.status_code == 200
    assert calls == []
