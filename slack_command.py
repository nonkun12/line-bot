"""Slack entrypoints for the guarded development workflow."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import parse_qs

import httpx
from flask import request

from line_development import dispatch_development_workflow

_MAX_BODY_AGE = 300
_DEVELOPMENT_PREFIXES = ("開発:", "dev:")


def _is_authorized_slack_user(user_id: str) -> bool:
    configured = os.environ.get("SLACK_DEV_ALLOWED_USER_IDS", "").strip()
    if not configured:
        configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and str(user_id) in allowed


def _verify_signature(body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
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


def _extract_development_instruction(text: str) -> str | None:
    normalized = str(text or "").strip()
    for prefix in _DEVELOPMENT_PREFIXES:
        if normalized.startswith(prefix):
            instruction = normalized[len(prefix):].strip()
            return instruction or None
    return None


def _slack_api(method: str, payload: dict) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return False
    try:
        response = httpx.post(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=8.0,
        )
        response.raise_for_status()
        data = response.json()
        return bool(data.get("ok"))
    except Exception:
        return False


def _post_message(channel_id: str, text: str) -> bool:
    return _slack_api("chat.postMessage", {"channel": channel_id, "text": text})


def _dispatch_instruction(instruction: str, user_id: str) -> str:
    return dispatch_development_workflow(
        instruction,
        user_id=user_id,
        token=os.environ.get("GITHUB_TOKEN", ""),
        repository=os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot"),
        authorized=True,
    )


def _verify_event_request(body: bytes) -> bool:
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    return bool(signing_secret) and _verify_signature(body, timestamp, signature, signing_secret)


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

        if not _is_authorized_slack_user(user_id):
            return {"response_type": "ephemeral", "text": "このSlackユーザーには開発権限がありません。"}, 403
        if not text:
            return {"response_type": "ephemeral", "text": "使い方: /dev ○○を実装して"}, 400

        instruction = _extract_development_instruction(text) or text
        reply = _dispatch_instruction(instruction, user_id)
        return {"response_type": "ephemeral", "text": reply}, 200

    @app.route("/slack/events", methods=["POST"])
    def slack_events():
        body = request.get_data(cache=False)
        if not _verify_event_request(body):
            return {"ok": False, "error": "invalid_signature"}, 401

        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            return {"ok": False, "error": "invalid_json"}, 400

        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}, 200

        if payload.get("type") != "event_callback":
            return {"ok": True}, 200

        event = payload.get("event") or {}
        if event.get("type") != "message":
            return {"ok": True}, 200
        if event.get("subtype") or event.get("bot_id") or event.get("bot_profile"):
            return {"ok": True}, 200

        user_id = str(event.get("user") or "").strip()
        channel_id = str(event.get("channel") or "").strip()
        text = str(event.get("text") or "").strip()
        instruction = _extract_development_instruction(text)
        if not user_id or not channel_id or not instruction:
            return {"ok": True}, 200
        if not _is_authorized_slack_user(user_id):
            _post_message(channel_id, "このSlackユーザーには開発権限がありません。")
            return {"ok": True}, 200

        _post_message(channel_id, "🚀 開発指示を受け付けました。GitHub Actionsで開発・テストを開始します。")
        reply = _dispatch_instruction(instruction, user_id)
        _post_message(channel_id, reply)
        return {"ok": True}, 200

    return slack_command
