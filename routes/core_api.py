"""Channel-independent API routes backed by the shared AI Gateway."""

from flask import Blueprint, current_app, jsonify, request
import hmac

from config import INTERNAL_PUSH_KEY
from core.channel import handle_channel_request

core_api_bp = Blueprint("core_api", __name__, url_prefix="/api")


@core_api_bp.route("/ask", methods=["POST"])
def ask():
    provided_key = request.headers.get("x-internal-key")
    if (
        not INTERNAL_PUSH_KEY
        or not provided_key
        or not hmac.compare_digest(str(provided_key), str(INTERNAL_PUSH_KEY))
    ):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    message = data.get("message")
    channel = data.get("channel", "web")

    if not user_id or not message:
        return jsonify({"ok": False, "error": "user_id and message are required"}), 400
    if not isinstance(channel, str) or not channel.strip():
        return jsonify({"ok": False, "error": "channel must be a non-empty string"}), 400

    try:
        response = handle_channel_request(
            current_app.ai_gateway,
            str(user_id),
            str(message),
            channel.strip(),
            metadata={"route": "api_ask"},
        )
        return jsonify(
            {
                "ok": True,
                "reply": response.text,
                "metadata": dict(response.metadata),
            }
        )
    except Exception as exc:
        current_app.logger.exception("CORE API ASK ERROR")
        return jsonify({"ok": False, "error": "internal server error"}), 500
