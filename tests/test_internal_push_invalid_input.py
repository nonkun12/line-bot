"""Tests for /internal/push input validation and successful push handling."""
import pytest
from types import SimpleNamespace

import app
import internal_ask_route


class _CapturingMessagingApi:
    calls = []
    quota_type = "limited"
    quota_value = 200
    total_usage = 0
    quota_error = None

    def __init__(self, api_client):
        pass

    def get_message_quota(self):
        self.calls.append(("quota", None))
        if self.quota_error:
            raise self.quota_error
        return SimpleNamespace(type=self.quota_type, value=self.quota_value)

    def get_message_quota_consumption(self):
        self.calls.append(("consumption", None))
        if self.quota_error:
            raise self.quota_error
        return SimpleNamespace(total_usage=self.total_usage)

    def reply_message(self, request):
        self.calls.append(("reply", request))

    def push_message(self, request):
        self.calls.append(("push", request))


@pytest.fixture
def capture_messaging_api(monkeypatch):
    _CapturingMessagingApi.calls = []
    _CapturingMessagingApi.quota_type = "limited"
    _CapturingMessagingApi.quota_value = 200
    _CapturingMessagingApi.total_usage = 0
    _CapturingMessagingApi.quota_error = None
    monkeypatch.setattr(internal_ask_route, "MessagingApi", _CapturingMessagingApi)
    yield _CapturingMessagingApi.calls


@pytest.fixture
def client():
    return app.app.test_client()


@pytest.fixture
def valid_headers():
    return {"x-internal-key": app.INTERNAL_PUSH_KEY}


USER_ID = "U19391b0b93be2f4d94284361153919ce"


def _assert_bad(client, payload, headers, calls):
    resp = client.post("/internal/push", json=payload, headers=headers)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert calls == []


def test_internal_push_missing_user_id_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"message": "テスト"}, valid_headers, capture_messaging_api)


def test_internal_push_null_user_id_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"user_id": None, "message": "テスト"}, valid_headers, capture_messaging_api)


def test_internal_push_empty_string_user_id_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"user_id": "", "message": "テスト"}, valid_headers, capture_messaging_api)


def test_internal_push_missing_message_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"user_id": USER_ID}, valid_headers, capture_messaging_api)


def test_internal_push_null_message_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"user_id": USER_ID, "message": None}, valid_headers, capture_messaging_api)


def test_internal_push_empty_string_message_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {"user_id": USER_ID, "message": ""}, valid_headers, capture_messaging_api)


def test_internal_push_empty_body_returns_400(client, valid_headers, capture_messaging_api):
    _assert_bad(client, {}, valid_headers, capture_messaging_api)


def test_internal_push_no_body_at_all_returns_400_not_500(client, valid_headers, capture_messaging_api):
    resp = client.post("/internal/push", headers=valid_headers)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_invalid_auth_key_returns_401(client, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": USER_ID, "message": "テスト"},
        headers={"x-internal-key": "wrong-key"},
    )
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_valid_input_still_returns_200_regression(client, valid_headers, capture_messaging_api, monkeypatch):
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)
    resp = client.post(
        "/internal/push",
        json={"user_id": USER_ID, "message": "テスト"},
        headers=valid_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert resp.get_json()["sent"] is True
    push_calls = [(kind, request) for kind, request in capture_messaging_api if kind == "push"]
    assert len(push_calls) == 1
    kind, request = push_calls[0]
    assert kind == "push"
    assert request.messages[0].text == "テスト"


def test_internal_push_skips_when_free_quota_reserve_would_be_breached(client, valid_headers, capture_messaging_api, monkeypatch):
    _CapturingMessagingApi.total_usage = 180
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    resp = client.post(
        "/internal/push",
        json={"user_id": USER_ID, "message": "test"},
        headers=valid_headers,
    )

    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True,
        "sent": False,
        "reason": "free_quota_safety_reserve",
        "usage": 180,
        "safe_limit": 200,
        "reserve": 20,
    }
    assert not any(kind == "push" for kind, _ in capture_messaging_api)


def test_internal_push_fails_closed_when_quota_api_is_unavailable(client, valid_headers, capture_messaging_api, monkeypatch):
    _CapturingMessagingApi.quota_error = RuntimeError("quota API unavailable")
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    resp = client.post(
        "/internal/push",
        json={"user_id": USER_ID, "message": "test"},
        headers=valid_headers,
    )

    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True,
        "sent": False,
        "reason": "quota_check_failed:RuntimeError",
    }
    assert not any(kind == "push" for kind, _ in capture_messaging_api)


def test_internal_push_skips_when_quota_is_not_limited(client, valid_headers, capture_messaging_api, monkeypatch):
    _CapturingMessagingApi.quota_type = "none"
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    resp = client.post(
        "/internal/push",
        json={"user_id": USER_ID, "message": "test"},
        headers=valid_headers,
    )

    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True,
        "sent": False,
        "reason": "quota_unavailable_or_unbounded",
    }
    assert not any(kind == "push" for kind, _ in capture_messaging_api)
