from io import BytesIO

from flask import Flask

from core.gateway import AIResponse
from routes.voice_api import voice_api_bp


def make_app():
    app = Flask(__name__)
    app.register_blueprint(voice_api_bp)
    app.ai_gateway = object()
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
    fake_gateway = object()

    import routes.voice_api as voice_api

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
    app = make_app()
    app.ai_gateway = fake_gateway

    response = app.test_client().post(
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


def test_voice_transcribe_requires_file(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    response = make_app().test_client().post(
        "/api/voice/transcribe",
        headers={"X-Internal-Key": "secret"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "file is required"


def test_voice_transcribe_uses_openai_adapter(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    captured = {}

    import routes.voice_api as voice_api

    def fake_transcribe(audio, filename, content_type):
        captured.update(audio=audio, filename=filename, content_type=content_type)
        return "今日の予定を教えて"

    monkeypatch.setattr(voice_api, "openai_transcribe_audio", fake_transcribe)
    response = make_app().test_client().post(
        "/api/voice/transcribe",
        data={"file": (BytesIO(b"audio-bytes"), "speech.webm")},
        headers={"X-Internal-Key": "secret"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "text": "今日の予定を教えて",
        "provider": "openai",
    }
    assert captured["audio"] == b"audio-bytes"
    assert captured["filename"] == "speech.webm"


def test_voice_speak_requires_internal_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    response = make_app().test_client().post(
        "/api/voice/speak",
        json={"text": "こんにちは"},
    )

    assert response.status_code == 401


def test_voice_speak_returns_audio(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")

    import routes.voice_api as voice_api

    monkeypatch.setattr(
        voice_api,
        "openai_tts_audio",
        lambda text: (b"fake-mp3", "audio/mpeg"),
    )
    response = make_app().test_client().post(
        "/api/voice/speak",
        json={"text": "こんにちは"},
        headers={"X-Internal-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"fake-mp3"


def test_voice_speak_rejects_empty_text(monkeypatch):
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "secret")
    response = make_app().test_client().post(
        "/api/voice/speak",
        json={},
        headers={"X-Internal-Key": "secret"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "text is required"
