"""LINE -> n8n / ai-app-builder delegation helpers.

This module intentionally contains no Flask route registration and no retry/dedup logic.
It keeps the existing n8n fire-and-forget path intact, while allowing an explicit,
opt-in application-builder path for app creation requests.
"""

from __future__ import annotations

import re
import time

import httpx

try:
    from e2e_status import record_step
except Exception:  # 監視層が使えなくても既存動作に影響させない
    def record_step(*args, **kwargs):
        pass

try:
    from config import (
        AI_APP_BUILDER_SHARED_SECRET,
        AI_APP_BUILDER_TIMEOUT_SECONDS,
        AI_APP_BUILDER_URL,
    )
except Exception:
    AI_APP_BUILDER_URL = ""
    AI_APP_BUILDER_SHARED_SECRET = ""
    AI_APP_BUILDER_TIMEOUT_SECONDS = 185.0


_APP_BUILDER_PATTERNS = (
    re.compile(r"アプリ.{0,12}(作って|つくって|作成|作れ|作りたい)"),
    re.compile(r"(web|ウェブ|WEB).{0,12}(アプリ|サービス).{0,12}(作って|つくって|作成)"),
    re.compile(r"(todo|ToDo|TODO).{0,12}(アプリ).{0,12}(作って|つくって|作成)"),
)


def is_ai_app_builder_request(message: str) -> bool:
    """Return True only for explicit app-building requests."""
    if not isinstance(message, str) or not message.strip():
        return False
    text = message.strip()
    return any(pattern.search(text) for pattern in _APP_BUILDER_PATTERNS)


def _push_line_reply(user_id: str, text: str) -> None:
    """Call the already-loaded Flask app's LINE push helper without import-time cycles."""
    from app import _line_push

    _line_push(user_id, text)


def _call_ai_app_builder(user_id: str, message: str) -> tuple[bool, str | None]:
    """Call ai-app-builder and return (handled, reply_text) without LINE push.

    ``handled`` is False only when AI_APP_BUILDER_URL is unset, allowing callers
    to fall back to the existing AI path.
    """
    if not AI_APP_BUILDER_URL:
        return False, None

    start = time.time()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if AI_APP_BUILDER_SHARED_SECRET:
        headers["x-shared-secret"] = AI_APP_BUILDER_SHARED_SECRET

    try:
        response = httpx.post(
            AI_APP_BUILDER_URL.rstrip("/") + "/interface/generate",
            json={"user_id": user_id, "message": message},
            headers=headers,
            timeout=AI_APP_BUILDER_TIMEOUT_SECONDS,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= response.status_code < 300
        record_step(
            "ai_app_builder",
            ok,
            http_status=response.status_code,
            response_time_ms=elapsed_ms,
            error=None if ok else f"ai-app-builder returned {response.status_code}",
        )

        if not ok:
            return True, f"アプリ作成サービスでエラーが発生しました。(HTTP {response.status_code})"

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("ai-app-builder returned invalid JSON")

        status = data.get("status", "failed")
        summary = str(data.get("summary") or "アプリ作成結果を取得できませんでした。")
        if status == "success":
            project_path = data.get("project_path")
            if project_path:
                summary = f"{summary}\n\n作成先: {project_path}"
        else:
            summary = f"アプリ作成に失敗しました。\n{summary}"

        return True, summary

    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        record_step(
            "ai_app_builder",
            False,
            response_time_ms=elapsed_ms,
            error=str(exc),
            error_location="_call_ai_app_builder",
        )
        return True, f"アプリ作成サービスへの接続に失敗しました。\n{type(exc).__name__}: {exc}"


def _delegate_to_ai_app_builder(user_id: str, message: str) -> bool:
    """Send an explicit app-building request to ai-app-builder and push its result to LINE."""
    handled, reply_text = _call_ai_app_builder(user_id, message)
    if handled:
        _push_line_reply(user_id, reply_text or "")
    return handled


def _delegate_to_n8n(user_id, message, webhook_url, timeout=5):
    """Delegate to ai-app-builder for explicit app requests; otherwise keep the n8n path unchanged."""
    if is_ai_app_builder_request(message) and _delegate_to_ai_app_builder(user_id, message):
        return

    start = time.time()
    try:
        res = httpx.post(
            webhook_url,
            json={"user_id": user_id, "message": message},
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= res.status_code < 300
        record_step(
            "n8n_webhook", ok,
            http_status=res.status_code,
            response_time_ms=elapsed_ms,
            error=None if ok else f"n8n webhook returned {res.status_code}",
        )
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        record_step(
            "n8n_webhook", False,
            response_time_ms=elapsed_ms,
            error=str(exc),
            error_location="_delegate_to_n8n",
        )
        print("N8N DELEGATE ERROR:", exc)
