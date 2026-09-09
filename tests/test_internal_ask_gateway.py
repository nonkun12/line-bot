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


def test_internal_ask_accepts_explicit_channel_for_future_adapters(monkeypatch):
    captured = {}

    def fake_handle(request):
        captured["request"] = request
        return AIResponse(text="voice reply")

    monkeypatch.setattr(app.app.ai_gateway, "handle", fake_handle)

    response = app.app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "音声テスト", "channel": "voice"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "reply": "voice reply"}
    request = captured["request"]
    assert request.channel == "voice"
    assert request.metadata["route"] == "internal_ask"


def test_internal_ask_rejects_blank_channel(monkeypatch):
    monkeypatch.setattr(app.app.ai_gateway, "handle", lambda request: AIResponse(text="unused"))

    response = app.app.test_client().post(
        "/internal/ask",
        json={"user_id": "u1", "message": "テスト", "channel": "   "},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "channel must be a non-empty string"}


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
    assert response.get_json() == {"ok": False, "error": "internal server error"}
    assert "gateway failure" not in response.get_data(as_text=True)
