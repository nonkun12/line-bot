"""Tests for /internal/push input validation and successful push handling."""
import pytest

import app
import internal_ask_route


class _CapturingMessagingApi:
    calls = []

    def __init__(self, api_client):
        pass

    def reply_message(self, request):
        self.calls.append(("reply", request))

    def push_message(self, request):
        self.calls.append(("push", request))


@pytest.fixture
def capture_messaging_api(monkeypatch):
    _CapturingMessagingApi.calls = []
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
    assert len(capture_messaging_api) == 1
    kind, request = capture_messaging_api[0]
    assert kind == "push"
    assert request.messages[0].text == "テスト"
