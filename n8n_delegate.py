"""LINE -> n8n / ai-app-builder delegation helpers."""

from __future__ import annotations

import re
import time
import httpx

try:
    from e2e_status import record_step
except Exception:
    def record_step(*args, **kwargs):
        pass

try:
    from config import AI_APP_BUILDER_SHARED_SECRET, AI_APP_BUILDER_TIMEOUT_SECONDS, AI_APP_BUILDER_URL
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
    if not isinstance(message, str) or not message.strip():
        return False
    return any(pattern.search(message.strip()) for pattern in _APP_BUILDER_PATTERNS)


def _push_line_reply(user_id: str, text: str) -> None:
    from app import _line_push
    _line_push(user_id, text)


def _call_ai_app_builder(user_id: str, message: str) -> tuple[bool, str | None]:
    if not AI_APP_BUILDER_URL:
        return False, None
    start = time.time()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if AI_APP_BUILDER_SHARED_SECRET:
        headers["x-shared-secret"] = AI_APP_BUILDER_SHARED_SECRET
    try:
        response = httpx.post(AI_APP_BUILDER_URL.rstrip("/") + "/interface/generate", json={"user_id": user_id, "message": message}, headers=headers, timeout=AI_APP_BUILDER_TIMEOUT_SECONDS)
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= response.status_code < 300
        record_step("ai_app_builder", ok, http_status=response.status_code, response_time_ms=elapsed_ms, error=None if ok else f"ai-app-builder returned {response.status_code}")
        if not ok:
            return True, f"アプリ作成サービスでエラーが発生しました。(HTTP {response.status_code})"
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("ai-app-builder returned invalid JSON")
        status = data.get("status", "failed")
        summary = str(data.get("summary") or "アプリ作成結果を取得できませんでした。")
        if status == "success" and data.get("project_path"):
            summary = f"{summary}\n\n作成先: {data['project_path']}"
        elif status != "success":
            summary = f"アプリ作成に失敗しました。\n{summary}"
        return True, summary
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        record_step("ai_app_builder", False, response_time_ms=elapsed_ms, error=str(exc), error_location="_call_ai_app_builder")
        return True, f"アプリ作成サービスへの接続に失敗しました。\n{type(exc).__name__}: {exc}"


def _delegate_to_ai_app_builder(user_id: str, message: str) -> bool:
    handled, reply_text = _call_ai_app_builder(user_id, message)
    if handled:
        _push_line_reply(user_id, reply_text or "")
    return handled


def _delegate_to_n8n(user_id, message, webhook_url, timeout=5):
    """Delegate to n8n and report success so the caller can safely fall back on failure."""
    if is_ai_app_builder_request(message) and _delegate_to_ai_app_builder(user_id, message):
        return True
    start = time.time()
    try:
        res = httpx.post(webhook_url, json={"user_id": user_id, "message": message}, timeout=timeout)
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= res.status_code < 300
        record_step("n8n_webhook", ok, http_status=res.status_code, response_time_ms=elapsed_ms, error=None if ok else f"n8n webhook returned {res.status_code}")
        return ok
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        record_step("n8n_webhook", False, response_time_ms=elapsed_ms, error=str(exc), error_location="_delegate_to_n8n")
        print("N8N DELEGATE ERROR:", exc)
        return False
