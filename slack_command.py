"""Slack slash-command entrypoints for guarded development and shared AI requests."""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from urllib.parse import parse_qs

import httpx
from flask import request

from line_development import dispatch_development_workflow

_MAX_BODY_AGE = 300
_SLACK_RESPONSE_TIMEOUT = 8.0


def _allowed_user_ids(env_name: str, fallback: str = "") -> set[str]:
    configured = os.environ.get(env_name, "").strip()
    if not configured and fallback:
        configured = os.environ.get(fallback, "").strip()
    return {item.strip() for item in configured.split(",") if item.strip()}


def _is_authorized_slack_user(user_id: str) -> bool:
    allowed = _allowed_user_ids("SLACK_DEV_ALLOWED_USER_IDS", "DEV_ALLOWED_USER_IDS")
    return bool(allowed) and str(user_id) in allowed


def _is_authorized_ai_user(user_id: str) -> bool:
    allowed = _allowed_user_ids(
        "SLACK_AI_ALLOWED_USER_IDS",
        "SLACK_DEV_ALLOWED_USER_IDS",
    )
    return bool(allowed) and str(user_id) in allowed


def _verify_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > _MAX_BODY_AGE:
        return False
    base = f"v0:{timestamp}:".encode("utf-8") + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return bool(signature) and hmac.compare_digest(expected, signature)


def _post_slack_response(response_url: str, text: str) -> None:
    """Deliver a delayed slash-command result through Slack's response URL."""
    if not response_url or not text.strip():
        return
    payload = {
        "response_type": "in_channel",
        "replace_original": False,
        "text": text[:3500],
    }
    try:
        response = httpx.post(
            response_url,
            json=payload,
            timeout=_SLACK_RESPONSE_TIMEOUT,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[slack] response delivery failed: {type(exc).__name__}: {exc}", flush=True)


def _dispatch_in_background(instruction: str, user_id: str) -> None:
    """Start GitHub dispatch without making Slack wait for the API round-trip."""
    reply = dispatch_development_workflow(
        instruction,
        user_id=user_id,
        token=os.environ.get("GITHUB_TOKEN", ""),
        repository=os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot"),
        authorized=True,
    )
    if reply and not reply.startswith("🚀"):
        print(f"[slack /dev] background dispatch result: {reply}", flush=True)


def _handle_ai_in_background(app, message: str, user_id: str, response_url: str) -> None:
    """Run the same channel-neutral AI Gateway used by LINE and post the final reply."""
    try:
        response = app.ai_gateway.handle(
            type("AIRequestCompat", (), {
                "user_id": str(user_id),
                "message": str(message),
                "channel": "slack",
                "metadata": {"route": "slack_ai"},
            })()
        )
        text = getattr(response, "text", "") or "AIからの応答がありませんでした。"
    except Exception as exc:
        print(f"[slack /ai] gateway failed: {type(exc).__name__}: {exc}", flush=True)
        text = "AIサービスで一時的な問題が発生しました。もう一度お試しください。"
    _post_slack_response(response_url, text)


def register_slack_command(app):
    @app.route("/slack/command", methods=["POST"])
    def slack_command():
        signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        body = request.get_data(cache=False)

        if not signing_secret or not _verify_signature(body, timestamp, signature, signing_secret):
            return {"response_type": "ephemeral", "text": "認証に失敗しました。"}, 401

        values = parse_qs(body.decode("utf-8", errors="replace"))
        user_id = (values.get("user_id") or [""])[0].strip()
        text = (values.get("text") or [""])[0].strip()
        command = (values.get("command") or [""])[0].strip()
        response_url = (values.get("response_url") or [""])[0].strip()

        if command == "/ai":
            if not _is_authorized_ai_user(user_id):
                return {
                    "response_type": "ephemeral",
                    "text": "このSlackユーザーにはAI利用権限がありません。",
                }, 403
            if not text:
                return {
                    "response_type": "ephemeral",
                    "text": "使い方: /ai AI NEWSとトヨタの株価をまとめて調べて",
                }, 400

            thread = threading.Thread(
                target=_handle_ai_in_background,
                args=(app, text, user_id, response_url),
                name="slack-ai-request",
                daemon=True,
            )
            thread.start()
            return {
                "response_type": "ephemeral",
                "text": "🔎 AI検索を受け付けました。結果をこのチャンネルへ返します。",
            }, 200

        if not _is_authorized_slack_user(user_id):
            return {
                "response_type": "ephemeral",
                "text": "このSlackユーザーには開発権限がありません。",
            }, 403
        if not text:
            return {"response_type": "ephemeral", "text": "使い方: /dev ○○を実装して"}, 400

        thread = threading.Thread(
            target=_dispatch_in_background,
            args=(text, user_id),
            name="slack-dev-dispatch",
            daemon=True,
        )
        thread.start()

        return {
            "response_type": "ephemeral",
            "text": "🚀 開発指示を受け付けました。GitHub Actionsで開発・テストを開始します。",
        }, 200

    return slack_command
