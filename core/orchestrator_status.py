"""Read-only LINE status for the single Orchestrator control plane."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable

import httpx

from scripts.orchestrator_live_adapter import SnapshotError, build_live_snapshot

_MAX_CONTENT_BYTES = 1024 * 1024
_STATUS_COMMANDS = {
    "統括ai状況確認",
    "統括aiの状況確認",
    "統括ai状況",
    "統括aiの状況",
    "統括aiステータス",
    "分散loop状況確認",
    "分散ループ状況確認",
    "orchestrator状況",
    "orchestratorの状況",
    "orchestratorstatus",
    "オーケストレーター状況確認",
}


def _normalize(message: str) -> str:
    value = unicodedata.normalize("NFKC", str(message or "")).casefold()
    return re.sub(r"[\s　]+", "", value).strip()


def is_orchestrator_status_command(message: str) -> bool:
    """Recognize explicit status requests only; never match start/run verbs."""
    return _normalize(message) in _STATUS_COMMANDS


def _get_json(url: str, *, token: str = "") -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.get(url, headers=headers, timeout=6.0)
    response.raise_for_status()
    return response.json()


def _decode_contents(payload: Any, label: str) -> tuple[Any, str]:
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise SnapshotError(f"{label}_contents_encoding_invalid")
    encoded = payload.get("content")
    if not isinstance(encoded, str):
        raise SnapshotError(f"{label}_contents_missing")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SnapshotError(f"{label}_contents_base64_invalid") from exc
    if len(raw) > _MAX_CONTENT_BYTES:
        raise SnapshotError(f"{label}_contents_too_large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{label}_contents_json_invalid") from exc
    return document, hashlib.sha256(raw).hexdigest()


def _fetch_repo_json(
    getter: Callable[..., Any],
    repository: str,
    path: str,
    ref: str,
    token: str,
    label: str,
) -> tuple[Any, str]:
    url = f"https://api.github.com/repos/{repository}/contents/{path}?ref={ref}"
    return _decode_contents(getter(url, token=token), label)


def build_orchestrator_status_reply(
    repository: str,
    token: str = "",
    *,
    get_json: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> str:
    """Read main queue/catalog and durable state; report blockers without writes."""
    repository = str(repository or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return _unavailable("GitHubリポジトリ設定が不正です")
    if not str(token or "").strip():
        return _unavailable("GitHub認証未設定")

    getter = get_json or _get_json
    try:
        queue, queue_sha = _fetch_repo_json(
            getter, repository, ".github/autonomous-loop-tasks.json", "main", token, "queue"
        )
        catalog, catalog_sha = _fetch_repo_json(
            getter, repository, ".github/autonomous-loop-task-catalog.json", "main", token, "catalog"
        )
        durable, state_sha = _fetch_repo_json(
            getter, repository, ".autonomous-loop-state.json", "autonomous-loop-state", token, "durable_state"
        )
        snapshot = build_live_snapshot(
            queue,
            catalog,
            durable,
            queue_sha256=queue_sha,
            catalog_sha256=catalog_sha,
            state_sha256=state_sha,
            now=now,
        )
    except Exception:
        return _unavailable("台帳または永続状態の証拠を検証できません")

    sources = snapshot["sources"]
    queue_counts: dict[str, int] = {}
    for task in snapshot["tasks"]:
        state = str(task.get("state") or "unknown")
        queue_counts[state] = queue_counts.get(state, 0) + 1

    hold = snapshot["global_hold"]
    budget = snapshot["budget"]
    hold_label = "HOLD_ACTIVE" if hold.get("active") is True else "未検証"
    budget_label = "未検証" if budget.get("verified") is not True else "検証済み"
    reasons = " / ".join(snapshot.get("reasons", [])) or "none"

    lines = [
        "【Orchestrator 単独状態】",
        "サブ4系統: CLOSED（再起動なし）",
        f"判定: {snapshot['status']}",
        (
            f"実キュー: {sources['runtime_queue_count']}件 "
            f"(完了 {queue_counts.get('completed', 0)} / "
            f"HOLD {queue_counts.get('held', 0)} / "
            f"レビュー待ち {queue_counts.get('review_required', 0)} / "
            f"未処理 {queue_counts.get('pending', 0)})"
        ),
        (
            f"タスクカタログ: {sources['catalog_count']}件 "
            f"(完了 {sources['catalog_completed_count']} / "
            f"HOLD {sources['catalog_held_count']} / "
            f"レビュー待ち {sources['catalog_review_required_count']} / "
            f"未分類 {sources['catalog_pending_count']})"
        ),
        f"永続状態: completed={sources['durable_completed_count']} / Recovery AI={sources['recovery_task_count']}",
        f"潜在候補: {snapshot['potential_candidate_count']}件 / 実行候補: {len(snapshot['candidate_ids'])}件",
        f"Global HOLD: {hold_label}",
        f"予算: {budget_label}（上限 {budget['limit_minutes']}分 / 使用量・残量は未検証）",
        "承認記録: 未検証",
        "実行許可: false",
        "Actions dispatch: false",
        f"Blocker: {reasons}",
        "これは読み取り専用の台帳スナップショットです。タスク実行・状態変更は行いません。",
        f"Queue SHA: {sources['runtime_queue_sha256'][:12]} / Catalog SHA: {sources['task_catalog_sha256'][:12]} / State SHA: {sources['durable_state_sha256'][:12]}",
    ]
    return "\n".join(lines)


def _unavailable(reason: str) -> str:
    return (
        "【Orchestrator 単独状態】\n"
        f"状態取得不可: {reason}\n"
        "判定: BLOCKED（成功・正常とは判定しません）\n"
        "実行許可: false / Actions dispatch: false"
    )


__all__ = ["build_orchestrator_status_reply", "is_orchestrator_status_command"]
