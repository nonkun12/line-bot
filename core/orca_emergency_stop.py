"""Shared terminal/LINE entrypoint for the durable Orca Emergency Stop."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

from scripts.orca_github_emergency_stop import activate_emergency_stop
from scripts.orca_github_state_store import GitHubStateStore, StateStoreError


def is_emergency_stop_command(message: str) -> bool:
    normalized = " ".join(str(message).strip().upper().split())
    return normalized in {"緊急停止", "ORCA STOP", "EMERGENCY STOP"} or normalized.startswith(
        ("緊急停止:", "ORCA STOP:", "EMERGENCY STOP:")
    )


def _reason(message: str) -> str:
    raw = str(message).strip()
    if ":" in raw:
        return raw.split(":", 1)[1].strip() or "human emergency stop"
    return "human emergency stop"


def _store():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = (
        os.environ.get("ORCA_STATE_REPOSITORY", "").strip()
        or os.environ.get("GITHUB_REPOSITORY", "").strip()
        or os.environ.get("AI_REPORT_GITHUB_REPO", "").strip()
    )
    branch = os.environ.get("ORCA_STATE_BRANCH", "").strip()
    path = os.environ.get("ORCA_STATE_PATH", "state/queue.json").strip()
    if not token or not repository or not branch or not path:
        raise StateStoreError("emergency_stop_state_store_configuration_missing")
    return GitHubStateStore(
        token=token, repository=repository, branch=branch, path=path,
    )


def activate_from_line(*, user_id: str, message: str) -> str:
    """Handle only exact STOP commands from a configured authorized LINE user."""
    allowed = {
        value.strip()
        for value in os.environ.get("DEV_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    }
    if not allowed or str(user_id) not in allowed:
        return "緊急停止要求を拒否しました。LINE利用者の許可リストが未設定、または権限がありません。"
    try:
        store = _store()
        snapshot = store.read()
        actor = "line:" + hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
        result = activate_emergency_stop(
            store=store, snapshot=snapshot, requested_by=actor,
            reason=_reason(message), event_id=uuid.uuid4().hex,
            now=datetime.now(timezone.utc), human_authorized=True,
        )
    except Exception as exc:
        return (
            "緊急停止を永続状態へ記録できませんでした。安全のため実行は許可されません。"
            f" 原因: {type(exc).__name__}"
        )
    status = result.get("status") if isinstance(result, dict) else None
    if status == "EMERGENCY_STOPPED":
        return (
            "🛑 Orca Emergency Stopを有効化しました。"
            "共通の永続STOP状態を記録済みです。自動解除はされません。"
        )
    if status == "ALREADY_STOPPED":
        return "🛑 Orcaは既にEmergency Stop状態です。停止状態を維持しています。"
    return "⚠️ Emergency Stopの永続化結果を確認できません。停止成功とは判定していません。実行は許可されません。"
