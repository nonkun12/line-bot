"""HTTP adapters for the voice/AI-speaker client."""

from __future__ import annotations

import hmac
import os

from flask import Blueprint, current_app, jsonify, request, send_file
from io import BytesIO

from core.channel import handle_channel_request
from core.voice import openai_transcribe_audio, openai_tts_audio


voice_api_bp = Blueprint("voice_api", __name__)


def _authorized() -> bool:
    expected = os.environ.get("INTERNAL_PUSH_KEY", "")
    provided = request.headers.get("X-Internal-Key", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided, expected)


@voice_api_bp.route("/api/voice", methods=["POST"])
def voice_api():
    """Handle a transcribed voice command through the shared AI Gateway."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    user_id = str(payload.get("user_id", "")).strip()
    message = str(payload.get("message", "")).strip()

    if not user_id or not message:
        return jsonify({"ok": False, "error": "user_id and message are required"}), 400

    try:
        response = handle_channel_request(
            current_app.ai_gateway,
            user_id,
            message,
            "voice",
            metadata={"route": "voice_api", "input": "speech_to_text"},
        )
    except Exception:
        current_app.logger.exception("VOICE API ERROR")
        return jsonify({"ok": False, "error": "internal server error"}), 500

    return jsonify({
        "ok": True,
        "reply": response.text,
        "metadata": dict(response.metadata),
    }), 200


@voice_api_bp.route("/api/voice/transcribe", methods=["POST"])
def voice_transcribe():
    """Transcribe an uploaded audio clip using the configured STT provider."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    upload = request.files.get("file")
    if upload is None:
        return jsonify({"ok": False, "error": "file is required"}), 400

    audio = upload.read()
    if not audio:
        return jsonify({"ok": False, "error": "file is empty"}), 400

    try:
        text = openai_transcribe_audio(
            audio,
            upload.filename or "speech.webm",
            upload.content_type,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError:
        return jsonify({"ok": False, "error": "voice service is not configured"}), 503
    except Exception:
        current_app.logger.exception("VOICE TRANSCRIBE ERROR")
        return jsonify({"ok": False, "error": "voice transcription failed"}), 502

    return jsonify({"ok": True, "text": text, "provider": "openai"}), 200


@voice_api_bp.route("/api/voice/speak", methods=["POST"])
def voice_speak():
    """Generate MP3 speech for text using the configured TTS provider."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False, "error": "text is required"}), 400

    try:
        audio, mime_type = openai_tts_audio(text)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError:
        return jsonify({"ok": False, "error": "voice service is not configured"}), 503
    except Exception:
        current_app.logger.exception("VOICE SPEECH ERROR")
        return jsonify({"ok": False, "error": "voice speech generation failed"}), 502

    return send_file(
        BytesIO(audio),
        mimetype=mime_type,
        as_attachment=False,
        download_name="speech.mp3",
        max_age=0,
    )
