from flask import jsonify, request
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

from n8n_delegate import is_ai_app_builder_request, _call_ai_app_builder
from config import configuration
from core.gateway import AIGateway, AIRequest
from linebot.v3.messaging import ApiClient, MessagingApi, PushMessageRequest, TextMessage

try:
    from e2e_status import StepTimer
except Exception:
    class StepTimer:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ok(self, *a, **k): pass
        def fail(self, *a, **k): pass


def _make_dashboard_url(user_id: str) -> str:
    timestamp = int(time.time())
    secret = os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""
    payload = f"{user_id}:{timestamp}"
    token = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    query = urlencode({"user_id": user_id, "ts": timestamp, "token": token})
    return f"https://line-bot-yvea.onrender.com/dashboard?{query}"


def register_internal_ask_route(app, internal_push_key, generate_reply_func):
    gateway = AIGateway(
        lambda ai_request: generate_reply_func(
            ai_request.user_id,
            ai_request.message,
        )
    )

    @app.route("/internal/ask", methods=["POST"])
    def internal_ask():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or not message:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        if str(message).strip() == "ダッシュボード":
            dashboard_url = _make_dashboard_url(str(user_id))
            return jsonify({"ok": True, "reply": f"ダッシュボードはこちらです。\n{dashboard_url}"})
        if is_ai_app_builder_request(message):
            handled, reply_text = _call_ai_app_builder(user_id, message)
            if handled:
                return jsonify({"ok": True, "reply": reply_text or ""})
        with StepTimer("internal_ask") as ask_timer, StepTimer("ai_mcp") as ai_timer:
            try:
                ai_response = gateway.handle(
                    AIRequest(
                        user_id=str(user_id),
                        message=str(message),
                        channel="http",
                        metadata={"route": "internal_ask"},
                    )
                )
                reply = ai_response.text
            except Exception as exc:
                print("INTERNAL ASK ERROR:", exc)
                ai_timer.fail(error=exc, error_location="generate_reply")
                ask_timer.fail(http_status=500, error=exc, error_location="internal_ask")
                return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
            ai_timer.ok(); ask_timer.ok(http_status=200)
        return jsonify({"ok": True, "reply": str(reply or "")})

    @app.route("/internal/push", methods=["POST"])
    def internal_push():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or message is None or not str(message).strip():
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        try:
            from app import _line_push
            _line_push(str(user_id), str(message))
            return jsonify({"ok": True})
        except Exception as exc:
            print("INTERNAL PUSH ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/internal/ai-report", methods=["POST"])
    def internal_ai_report():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "error": "user_id is required"}), 400
        try:
            from app import generate_ai_secretary_report, _line_push
            report = generate_ai_secretary_report(str(user_id))
            _line_push(str(user_id), str(report or ""))
            return jsonify({"ok": True})
        except Exception as exc:
            print("INTERNAL AI REPORT ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return internal_ask
