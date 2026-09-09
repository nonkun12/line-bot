import app
from core.gateway import AIResponse


def _headers():
    return {"x-internal-key": app.INTERNAL_PUSH_KEY}


def test_internal_ask_routes_request_through_ai_gateway(monkeypatch):
    captured = {}

    def fake_handle(request):
        captured["request"] = request
        return AIResponse(text="gateway reply")

    monkeypatch.setattr(app.app.ai_gateway, "handle", fake_handle)

    response = app.app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "こんにちは"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "reply": "gateway reply"}
    request = captured["request"]
    assert request.user_id == "u1"
    assert request.message == "こんにちは"
    assert request.channel == "http"
    assert request.metadata["route"] == "internal_ask"


def test_internal_ask_gateway_error_returns_500(monkeypatch):
    def fake_handle(request):
        raise RuntimeError("gateway failure")

    monkeypatch.setattr(app.app.ai_gateway, "handle", fake_handle)

    response = app.app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "テスト"},
        headers=_headers(),
    )

    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert "gateway failure" in body["error"]
