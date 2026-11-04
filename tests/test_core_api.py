from flask import Flask

from core.gateway import AIResponse
from routes.core_api import core_api_bp


def make_app():
    app = Flask(__name__)
    app.register_blueprint(core_api_bp)
    app.ai_gateway = object()
    return app


def test_core_api_ask_requires_internal_key(monkeypatch):
    monkeypatch.setattr("routes.core_api.INTERNAL_PUSH_KEY", "secret")
    response = make_app().test_client().post(
        "/api/ask",
        json={"user_id": "U1", "message": "映像シナリオを作って"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


def test_core_api_ask_returns_gateway_metadata_for_artifact_consumers(monkeypatch):
    monkeypatch.setattr("routes.core_api.INTERNAL_PUSH_KEY", "secret")

    class FakeGateway:
        def handle(self, request):
            return AIResponse(
                text="映像・音楽の制作設計ができました",
                metadata={
                    "intent": "distributed_video_music_pipeline",
                    "route": "distributed:video→music",
                    "specialists": ["video", "music"],
                    "video_music_artifacts": {
                        "rendering_status": "midi_generated_audio_not_rendered",
                        "midi_artifact": {
                            "filename": "test.mid",
                            "mime_type": "audio/midi",
                            "encoding": "base64",
                            "content_base64": "TVRoZ",
                        },
                    },
                },
            )

    app = make_app()
    app.ai_gateway = FakeGateway()
    response = app.test_client().post(
        "/api/ask",
        json={"user_id": "U1", "message": "映像と音楽のシナリオを作って"},
        headers={"x-internal-key": "secret"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["reply"] == "映像・音楽の制作設計ができました"
    assert payload["metadata"]["route"] == "distributed:video→music"
    assert payload["metadata"]["video_music_artifacts"]["midi_artifact"]["mime_type"] == "audio/midi"
