"""Slack slash-command entrypoint for the guarded development workflow."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import parse_qs

from flask import request

from line_development import dispatch_development_workflow

_MAX_BODY_AGE = 300


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

        instruction = text
        if instruction.startswith(("開発:", "dev:")):
            instruction = instruction.split(":", 1)[1].strip()
        reply = dispatch_development_workflow(
            instruction,
            user_id=user_id,
            token=os.environ.get("GITHUB_TOKEN", ""),
            repository=os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot"),
            authorized=True,
        )
        return {"response_type": "ephemeral", "text": reply}, 200

    return slack_command
