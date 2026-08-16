"""/internal/push の異常系(入力不備)テスト。

過去に、user_id/message が None・欠落・空文字の場合でも、バリデーション
チェック(`if not user_id or not message`)より前で `len(user_id)` を
呼び出すデバッグログが実行されていたため、TypeError が発生し
意図しない500(内部サーバーエラー)になっていた。

このテストは、以下のケースで必ず200ではなく400が返り、かつLINEへの
送信(push_message)が一切実行されないことを固定して再発を防ぐ。
"""
import pytest

import app


class _CapturingMessagingApi:
    """MessagingApi(api) の呼び出しを記録するフェイク。"""
    calls = []

    def __init__(self, api_client):
        pass

    def reply_message(self, request):
        _CapturingMessagingApi.calls.append(("reply", request))

    def push_message(self, request):
        _CapturingMessagingApi.calls.append(("push", request))


@pytest.fixture
def capture_messaging_api(monkeypatch):
    _CapturingMessagingApi.calls = []
    monkeypatch.setattr(app, "MessagingApi", _CapturingMessagingApi)
    yield _CapturingMessagingApi.calls


@pytest.fixture
def client():
    return app.app.test_client()


@pytest.fixture
def valid_headers():
    return {"x-internal-key": app.INTERNAL_PUSH_KEY}


def test_internal_push_missing_user_id_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"message": "テスト"},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_null_user_id_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": None, "message": "テスト"},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_empty_string_user_id_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": "", "message": "テスト"},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_missing_message_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce"},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_null_message_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": None},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_empty_string_message_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": ""},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_empty_body_returns_400(client, valid_headers, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={},
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_no_body_at_all_returns_400_not_500(client, valid_headers, capture_messaging_api):
    """Content-Typeなし/JSONなしのPOSTでもクラッシュせず400を返すこと。"""
    resp = client.post(
        "/internal/push",
        headers=valid_headers,
    )

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_invalid_auth_key_returns_401(client, capture_messaging_api):
    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": "テスト"},
        headers={"x-internal-key": "wrong-key"},
    )

    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False
    assert capture_messaging_api == []


def test_internal_push_valid_input_still_returns_200_regression(client, valid_headers, capture_messaging_api, monkeypatch):
    """異常系対応がリグレッションを起こしていないことの確認(正常系は従来通り200)。"""
    monkeypatch.setattr(app, "save_message", lambda *a, **k: None)

    resp = client.post(
        "/internal/push",
        json={"user_id": "U19391b0b93be2f4d94284361153919ce", "message": "テスト"},
        headers=valid_headers,
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    calls = capture_messaging_api
    assert len(calls) == 1
    kind, request = calls[0]
    assert kind == "push"
    assert request.messages[0].text == "テスト"
