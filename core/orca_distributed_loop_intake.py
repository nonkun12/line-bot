"""Owner-bound LINE intake and approval for typed ORCA distributed-loop tasks.

The route registers work only. It never claims, dispatches, or executes a loop.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from distributed_loop_trigger import _requested_max_tasks

_LINE_USER_ID_RE = re.compile(r"^U[0-9a-fA-F]{32}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_APPROVE_PREFIXES = ("分散Loop承認:", "分散Loop承認：")


def _allowed_users() -> set[str]:
    return {
        item.strip()
        for item in os.environ.get("DISTRIBUTED_LOOP_LINE_USER_IDS", "").split(",")
        if item.strip()
    }


def build_distributed_loop_task_payload(
    *,
    task_id: str,
    request_text: str,
    source_event_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """Build a typed, owner-bound payload for an exact, bounded loop command."""
    if not isinstance(user_id, str) or _LINE_USER_ID_RE.fullmatch(user_id) is None:
        raise ValueError("verified LINE user ID is required")
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError("invalid ORCA task ID")
    if not isinstance(source_event_id, str) or not source_event_id.strip():
        raise ValueError("LINE source event ID is required")
    if not isinstance(request_text, str) or not request_text.strip():
        raise ValueError("distributed-loop command is required")
    max_tasks = _requested_max_tasks(request_text)
    if max_tasks is None:
        raise ValueError("unrecognized distributed-loop command or missing safety confirmation")
    return {
        "task_id": task_id,
        "task_type": "distributed_loop",
        "request_text": request_text,
        "max_tasks": max_tasks,
        "source_event_id": source_event_id,
        "user_id": user_id,
    }


def _approval_v2(task_id: str, request_text: str, user_id: str, max_tasks: int, secret: str) -> dict[str, Any]:
    if not _TASK_ID_RE.fullmatch(task_id) or not _LINE_USER_ID_RE.fullmatch(user_id):
        raise ValueError("invalid task or LINE owner")
    if not isinstance(max_tasks, int) or isinstance(max_tasks, bool) or not 1 <= max_tasks <= 4:
        raise ValueError("invalid distributed-loop task bound")
    if _requested_max_tasks(request_text) != max_tasks:
        raise ValueError("stored command does not match the task bound")
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("approval HMAC secret is not configured securely")
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    expires = issued + timedelta(hours=1)
    issued_at = issued.isoformat().replace("+00:00", "Z")
    expires_at = expires.isoformat().replace("+00:00", "Z")
    request_hash = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
    nonce = secrets.token_urlsafe(24)
    canonical = "\n".join((
        "v2", task_id, request_hash, user_id, "distributed_loop",
        str(max_tasks), issued_at, expires_at, nonce,
    ))
    signature = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "approver_user_id": user_id,
        "request_hash": request_hash,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
        "signature": signature,
        "task_type": "distributed_loop",
        "max_tasks": max_tasks,
    }


def register_distributed_loop(
    message: str, message_id: str, user_id: str | None,
    api_url: str, api_token: str,
):
    """Return None for unrelated text; otherwise (reply, retryable)."""
    max_tasks = _requested_max_tasks(message)
    if max_tasks is None:
        return None
    if not isinstance(user_id, str) or user_id not in _allowed_users():
        return ("分散Loopの受付は許可されていません。このLINEユーザーには操作権限がありません。", False)
    if not api_url or not api_token:
        return ("Orca D1受付設定が未完了です。分散Loopは登録されていません。", False)
    task_id = f"line-loop-{uuid.uuid4().hex}"
    try:
        payload = build_distributed_loop_task_payload(
            task_id=task_id, request_text=message,
            source_event_id=message_id, user_id=user_id,
        )
        response = httpx.post(
            api_url.rstrip("/") + "/tasks", json=payload,
            headers={"Authorization": f"Bearer {api_token}"}, timeout=8.0,
        )
    except (ValueError, httpx.TransportError):
        return ("分散Loop受付に失敗しました。登録状態を確認できないため、時間をおいて再確認してください。", True)
    if response.status_code >= 500:
        return ("Orca D1で一時エラーが発生しました。登録状態は未確認です。再確認してください。", True)
    if response.status_code not in (200, 201):
        return (f"分散Loop受付が拒否されました（HTTP {response.status_code}）。実行は開始していません。", False)
    try:
        body = response.json()
        task = body.get("task", body) if isinstance(body, dict) else None
        if (not isinstance(task, dict) or task.get("task_id") != task_id
                or task.get("task_type") != "distributed_loop"
                or task.get("max_tasks") != max_tasks
                or task.get("status") != "queued"):
            raise ValueError("unexpected typed task response")
    except (ValueError, AttributeError):
        return ("D1応答を検証できませんでした。登録状態を確認してから再送してください。", True)
    return (
        f"分散LoopをD1に受付しました（未実行）。Task ID: {task_id} / 上限: {max_tasks}回。"
        f"実行承認する場合は「分散Loop承認:{task_id}」を送ってください。", False,
    )


def approve_distributed_loop(
    message: str, user_id: str | None, api_url: str, api_token: str, approval_secret: str,
):
    """Approve only a typed distributed-loop task owned by the verified LINE user."""
    prefix = next((item for item in _APPROVE_PREFIXES if message.startswith(item)), None)
    if prefix is None:
        return None
    task_id = message[len(prefix):].strip()
    if not _TASK_ID_RE.fullmatch(task_id):
        return ("Task IDの形式が正しくありません。承認していません。", False)
    if not isinstance(user_id, str) or user_id not in _allowed_users():
        return ("分散Loop承認は許可されていません。承認していません。", False)
    if not api_url or not api_token or len(approval_secret.encode("utf-8")) < 32:
        return ("分散Loop承認の安全設定が未完了です。承認していません。", False)
    url = api_url.rstrip("/") + "/tasks/" + task_id
    headers = {"Authorization": f"Bearer {api_token}"}
    try:
        response = httpx.get(url, headers=headers, timeout=8.0)
        if response.status_code != 200:
            return (f"対象タスクを取得できません（HTTP {response.status_code}）。承認していません。", False)
        result = response.json()
        task = result.get("task") if isinstance(result, dict) else None
        if not isinstance(task, dict):
            return ("タスク応答が不正です。承認していません。", False)
        request_text = task.get("request_text")
        max_tasks = task.get("max_tasks")
        if (task.get("task_id") != task_id or task.get("status") not in ("queued", "running")
                or task.get("task_type") != "distributed_loop"):
            return ("対象は承認可能な分散Loopタスクではありません。承認していません。", False)
        payload = _approval_v2(task_id, request_text, user_id, max_tasks, approval_secret)
        approved = httpx.post(url + "/approve", json=payload, headers=headers, timeout=8.0)
    except (httpx.TransportError, ValueError, TypeError, AttributeError):
        return ("分散Loop承認APIとの通信または応答検証に失敗しました。承認していません。", True)
    if approved.status_code != 200:
        return (f"分散Loop承認は拒否されました（HTTP {approved.status_code}）。", False)
    try:
        approval = approved.json()
    except ValueError:
        return ("承認結果を確認できませんでした。状態を照会してください。", True)
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        return ("承認結果を確認できませんでした。状態を照会してください。", True)
    return (f"分散Loopタスク {task_id} を承認しました（上限 {max_tasks}回）。専用Worker実装前のため、まだ実行されません。", False)
