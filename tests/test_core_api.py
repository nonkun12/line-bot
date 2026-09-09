import app
from core.gateway import AIResponse


def _headers():
    return {"x-internal-key": app.INTERNAL_PUSH_KEY}


def test_core_api_ask_uses_shared_gateway(monkeypatch):
    captured = {}

    def fake_handle(request):
        captured["request"] = request
        return AIResponse(text="web reply", metadata={"source": "test"})

    monkeypatch.setattr(app.app.ai_gateway, "handle", fake_handle)

    response = app.app.test_client().post(
        "/api/ask",
        json={"user_id": "u1", "message": "こんにちは"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "reply": "web reply",
        "metadata": {"source": "test"},
    }
    request = captured["request"]
    assert request.user_id == "u1"
    assert request.message == "こんにちは"
    assert request.channel == "web"
    assert request.metadata["route"] == "api_ask"


def test_core_api_ask_accepts_future_channel(monkeypatch):
    captured = {}

    def fake_handle(request):
        captured["request"] = request
        return AIResponse(text="voice reply")

    monkeypatch.setattr(app.app.ai_gateway, "handle", fake_handle)

    response = app.app.test_client().post(
        "/api/ask",
        json={"user_id": "u1", "message": "音声テスト", "channel": "voice"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "reply": "voice reply", "metadata": {}}
    assert captured["request"].channel == "voice"


def test_core_api_ask_requires_authentication():
    response = app.app.test_client().post(
        "/api/ask",
        json={"user_id": "u1", "message": "test"},
    )
    assert response.status_code == 401
    assert response.get_json() == {"ok": False, "error": "unauthorized"}


def test_core_api_ask_rejects_blank_channel(monkeypatch):
    monkeypatch.setattr(app.app.ai_gateway, "handle", lambda request: AIResponse(text="unused"))

    response = app.app.test_client().post(
        "/api/ask",
        json={"user_id": "u1", "message": "test", "channel": "   "},
        headers=_headers(),
    )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "channel must be a non-empty string"}
