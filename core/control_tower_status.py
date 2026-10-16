"""Deterministic, read-only status reply for explicit Control Tower LINE commands."""
from __future__ import annotations

import os
from typing import Any, Callable

import httpx

_STATUS_COMMANDS = {
    "統括ai 状況確認",
    "統括aiの状況確認",
    "統括ai ステータス",
    "統括ai 状況",
    "分散loop 状況確認",
    "分散ループ 状況確認",
}


def is_control_tower_status_command(message: str) -> bool:
    normalized = " ".join(str(message or "").strip().casefold().split())
    return normalized in _STATUS_COMMANDS


def build_control_tower_status_reply(
    repository: str,
    token: str = "",
    *,
    get_json: Callable[..., Any] | None = None,
) -> str:
    """Report evidence from GitHub Actions; never infer task counts or success."""
    repository = str(repository or "").strip()
    if not repository or "/" not in repository:
        return _unavailable("GitHubリポジトリ設定が不正です")

    getter = get_json or _get_json
    url = f"https://api.github.com/repos/{repository}/actions/workflows/distributed-autonomous-loop.yml/runs?per_page=1"
    try:
        payload = getter(url, token=token)
        runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
        run = runs[0] if runs and isinstance(runs[0], dict) else None
    except Exception:
        run = None

    lines = [
        "【統括AI 状況確認】",
        f"対象リポジトリ: {repository}",
    ]
    if run is None:
        lines.extend([
            "分散Loop: 最新実行結果を取得できません（成功とは判定しません）",
            "Task ID／キュー件数: 未取得",
        ])
    else:
        status = str(run.get("status") or "unknown").lower()
        conclusion = str(run.get("conclusion") or "").lower()
        if status != "completed":
            state = f"実行中（{status}）"
        elif conclusion == "success":
            state = "GitHub Actions上は成功"
        elif conclusion:
            state = f"失敗または未合格（{conclusion}）"
        else:
            state = "完了状態を確認できません"
        lines.extend([
            f"分散Loop: {state}",
            f"最新Run: #{run.get('run_number', '不明')} / {run.get('name') or '名称未取得'}",
            f"開始: {run.get('created_at') or '未取得'}",
            f"実行イベント: {run.get('event') or '未取得'}",
            f"Run URL: {run.get('html_url') or '未取得'}",
            "Task ID／キュー件数: Run概要からは未取得（推測しません）",
        ])

    patch_setting = os.environ.get("AUTO_APPLY_PATCH", "false").strip().lower()
    deploy_setting = os.environ.get("AUTO_DEPLOY", "false").strip().lower()
    lines.extend([
        f"自動パッチ適用: {'有効' if patch_setting in {'1', 'true', 'yes', 'on'} else '無効'}",
        f"自動デプロイ: {'有効' if deploy_setting in {'1', 'true', 'yes', 'on'} else '無効'}",
        "判定: この報告は読み取り専用。マージ／デプロイは実行しません。",
    ])
    return "\n".join(lines)


def _get_json(url: str, *, token: str = "") -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.get(url, headers=headers, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _unavailable(reason: str) -> str:
    return (
        "【統括AI 状況確認】\n"
        f"状態取得不可: {reason}\n"
        "成功・正常とは判定しません。マージ／デプロイは実行しません。"
    )
