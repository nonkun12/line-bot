"""LINE -> GitHub Actions dispatcher for autonomous app development."""
from __future__ import annotations

import os
import re

import httpx

_APP_PREFIX = re.compile(r"^(?:アプリ開発|app|app-dev)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
_APP_REQUEST = re.compile(r"(?:アプリ|webアプリ|ウェブアプリ).{0,20}(?:作って|つくって|作成|作れ|開発して|開発)", re.IGNORECASE | re.DOTALL)
_MAX_REQUIREMENT_LENGTH = 3000
_WORKFLOW_FILE = "app-development.yml"


def extract_app_development_request(message: str) -> str | None:
    text = str(message or "").strip()
    match = _APP_PREFIX.match(text)
    if match:
        requirement = match.group(1).strip()
        return requirement[:_MAX_REQUIREMENT_LENGTH] if requirement else ""
    if _APP_REQUEST.search(text):
        return text[:_MAX_REQUIREMENT_LENGTH]
    return None


def _is_authorized_user(user_id: str) -> bool:
    configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and str(user_id) in allowed


def dispatch_app_development_workflow(requirement: str, *, user_id: str, token: str | None = None) -> str:
    requirement = str(requirement or "").strip()
    if not requirement:
        return "アプリ開発の要件が空です。『アプリ開発: ○○を作って』の形式で指定してください。"
    if not _is_authorized_user(user_id):
        return "このLINEユーザーにはアプリ開発ワークフローの実行権限がありません。"
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "アプリ開発を起動できません。GITHUB_TOKENが設定されていません。"
    repository = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{_WORKFLOW_FILE}/dispatches"
    payload = {"ref": "main", "inputs": {"requirement": requirement, "user_id": str(user_id)}}
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
    except Exception as exc:
        return f"アプリ開発ワークフローの起動に失敗しました: {type(exc).__name__}"
    if response.status_code not in (200, 201, 202, 204):
        return f"アプリ開発ワークフローの起動に失敗しました (GitHub HTTP {response.status_code})。"
    return (
        "🚀 アプリ開発を開始しました。\n"
        f"要件: {requirement}\n"
        "AIが設計・実装・テスト・修正・PR作成まで自動で進めます。\n"
        "完了または失敗したらLINEへ通知します。"
    )
