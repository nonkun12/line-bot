from flask import jsonify, request
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

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
    if not secret:
        return ""
    payload = f"{user_id}:{timestamp}"
    token = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    query = urlencode({"user_id": user_id, "ts": timestamp, "token": token})
    return f"https://line-bot-yvea.onrender.com/dashboard?{query}"


def register_internal_ask_route(app, internal_push_key, generate_reply_func):
    @app.route("/internal/ask", methods=["POST"])
    def internal_ask():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id", "")).strip()
        message = str(data.get("message", "")).strip()
        if not user_id or not message:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        if message == "ダッシュボード":
            dashboard_url = _make_dashboard_url(user_id)
            if not dashboard_url:
                return jsonify({"ok": False, "error": "dashboard link is not configured"}), 503
            return jsonify({"ok": True, "reply": f"ダッシュボードはこちらです。\n{dashboard_url}"})
        with StepTimer("internal_ask") as ask_timer, StepTimer("ai_mcp") as ai_timer:
            try:
                reply = generate_reply_func(user_id, message)
            except Exception:
                print("INTERNAL ASK ERROR", flush=True)
                ai_timer.fail(error="internal server error", error_location="generate_reply")
                ask_timer.fail(http_status=500, error="internal server error", error_location="internal_ask")
                return jsonify({"ok": False, "error": "internal server error"}), 500
            ai_timer.ok(); ask_timer.ok(http_status=200)
        return jsonify({"ok": True, "reply": str(reply or "")})

    @app.route("/internal/push", methods=["POST"])
    def internal_push():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id", "")).strip()
        message = str(data.get("message", "")).strip()
        if not user_id or not message:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        try:
            from app import _build_line_messages

            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=_build_line_messages(message),
                    )
                )
            return jsonify({"ok": True})
        except Exception:
            print("INTERNAL PUSH ERROR", flush=True)
            return jsonify({"ok": False, "error": "internal server error"}), 500

    @app.route("/internal/create-pr", methods=["POST"])
    def internal_create_pr():
        provided_key = request.headers.get("x-internal-key")
        if not internal_push_key or not provided_key or not hmac.compare_digest(str(provided_key), str(internal_push_key)):
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        head = str(data.get("head") or "").strip()
        title = str(data.get("title") or "feat: LINE development request").strip()
        body = str(data.get("body") or "").strip()
        repository = str(data.get("repository") or os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")).strip()
        token = os.environ.get("GH_PR_TOKEN", "").strip()
        if not head:
            return jsonify({"ok": False, "error": "head is required"}), 400
        if not token:
            return jsonify({"ok": False, "error": "GH_PR_TOKEN is not configured"}), 500

        url = f"https://api.github.com/repos/{repository}/pulls"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {"title": title, "head": head, "base": "main", "body": body}
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        except Exception as exc:
            print(f"GitHub PR request failed: {type(exc).__name__}", flush=True)
            return jsonify({"ok": False, "error": "GitHub request failed"}), 502

        if response.status_code in (200, 201):
            result = response.json()
            return jsonify({"ok": True, "number": result.get("number"), "url": result.get("html_url")}), 201
        if response.status_code == 422:
            return jsonify({"ok": False, "error": "GitHub rejected PR creation"}), 422
        print(f"GitHub PR HTTP {response.status_code}", flush=True)
        return jsonify({"ok": False, "error": "GitHub request failed"}), 502

    return internal_ask
