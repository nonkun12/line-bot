from flask import Flask

from core.gateway import AIResponse
from routes.voice_api import voice_api_bp


def make_app():
    app = Flask(__name__)
    app.register_blueprint(voice_api_bp)
    return app


def test_voice_api_requires_internal_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    client = make_app().test_client()

    response = client.post("/api/voice", json={"user_id": "U1", "message": "今日の予定"})

    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


def test_voice_api_rejects_missing_fields(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    client = make_app().test_client()

    response = client.post(
        "/api/voice",
        json={"user_id": "U1"},
        headers={"X-Internal-Key": "secret"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "user_id and message are required"


def test_voice_api_uses_shared_gateway(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    captured = {}

    class FakeGateway:
        pass

    fake_gateway = FakeGateway()

    import routes.voice_api as voice_api

    class FakeApp:
        ai_gateway = fake_gateway

    monkeypatch.setattr(voice_api, "__import__", lambda name: FakeApp() if name == "app" else __import__(name))

    def fake_handle(gateway, user_id, message, channel, *, metadata=None):
        captured.update(
            gateway=gateway,
            user_id=user_id,
            message=message,
            channel=channel,
            metadata=metadata,
        )
        return AIResponse(text="了解しました", metadata={"source": "test"})

    monkeypatch.setattr(voice_api, "handle_channel_request", fake_handle)
    client = make_app().test_client()

    response = client.post(
        "/api/voice",
        json={"user_id": "U1", "message": "今日の予定を教えて"},
        headers={"X-Internal-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "reply": "了解しました",
        "metadata": {"source": "test"},
    }
    assert captured["gateway"] is fake_gateway
    assert captured["user_id"] == "U1"
    assert captured["message"] == "今日の予定を教えて"
    assert captured["channel"] == "voice"
    assert captured["metadata"]["input"] == "speech_to_text"
