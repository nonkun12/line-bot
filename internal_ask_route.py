from flask import jsonify, request
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

from n8n_delegate import is_ai_app_builder_request, _call_ai_app_builder
from config import configuration
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
    @app.route("/internal/ask", methods=["POST"])
    def internal_ask():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or not message:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400

        if str(message).strip() == "ダッシュボード":
            dashboard_url = _make_dashboard_url(str(user_id))
            return jsonify({"ok": True, "reply": f"ダッシュボードはこちらです。\n{dashboard_url}"})

        # 明示的な開発依頼は通常の会話回答に流さずJob化する。
        try:
            from development_jobs import is_development_request, enqueue_development_job
            if is_development_request(str(message)):
                job = enqueue_development_job(str(user_id), str(message))
                reply = f"開発タスクとして登録しました。\nJob ID: {job['job_id']}\n夜間に自動開発を進めます。"
                return jsonify({"ok": True, "reply": reply, "job": job})
        except Exception as exc:
            print("DEVELOPMENT JOB ENQUEUE ERROR:", exc)
            return jsonify({"ok": False, "error": f"DevelopmentJobError: {exc}"}), 500

        if is_ai_app_builder_request(message):
            handled, reply_text = _call_ai_app_builder(user_id, message)
            if handled:
                return jsonify({"ok": True, "reply": reply_text or ""})

        with StepTimer("internal_ask") as ask_timer, StepTimer("ai_mcp") as ai_timer:
            try:
                reply = generate_reply_func(user_id, message)
            except Exception as exc:
                print("INTERNAL ASK ERROR:", exc)
                ai_timer.fail(error=exc, error_location="generate_reply")
                ask_timer.fail(http_status=500, error=exc, error_location="internal_ask")
                return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
            ai_timer.ok()
            ask_timer.ok(http_status=200)
        return jsonify({"ok": True, "reply": str(reply or "")})

    @app.route("/internal/job-worker", methods=["POST"])
    def internal_job_worker():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            from job_worker import run_once
            result = run_once()
            return jsonify({"ok": True, "job": result})
        except Exception as exc:
            print("JOB WORKER ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/internal/push", methods=["POST"])
    def internal_push():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or message is None:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        try:
            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(PushMessageRequest(to=str(user_id), messages=[TextMessage(text=str(message))]))
            return jsonify({"ok": True})
        except Exception as exc:
            print("INTERNAL PUSH ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return internal_ask
