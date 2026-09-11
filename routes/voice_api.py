"""HTTP adapter for the future voice/AI-speaker client.

This endpoint accepts a speech-to-text result and sends it through the same
channel-independent AI Gateway used by LINE. Audio transport and TTS stay
outside this server for now so the core assistant remains unchanged.
"""

from __future__ import annotations

import hmac
import os

from flask import Blueprint, jsonify, request

from core.channel import handle_channel_request


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
            __import__("app").app.ai_gateway,
            user_id,
            message,
            "voice",
            metadata={"route": "voice_api", "input": "speech_to_text"},
        )
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }), 500

    return jsonify({
        "ok": True,
        "reply": response.text,
        "metadata": dict(response.metadata),
    }), 200
