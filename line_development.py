"""Explicit LINE -> GitHub Actions development command dispatcher.

Only messages beginning with ``開発:`` or ``dev:`` are accepted for the
normal development worker. App-development requests are owned by the Core
Supervisor/Agent path and are intentionally not handled here.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import httpx


_DEV_PREFIX = re.compile(r"^(?:開発|dev)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
_MAX_INSTRUCTION_LENGTH = 2000
_WORKFLOW_FILE = "line-development.yml"


def extract_development_instruction(message: str) -> Optional[str]:
    """Return the explicit normal development instruction, or None."""
    text = str(message or "").strip()
    match = _DEV_PREFIX.match(text)
    if not match:
        return None
    instruction = match.group(1).strip()
    if not instruction:
        return ""
    return instruction[:_MAX_INSTRUCTION_LENGTH]


def _is_authorized_user(user_id: str) -> bool:
    """Require an explicit allowlist; deny by default when it is not configured."""
    configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and str(user_id) in allowed


def dispatch_development_workflow(
    instruction: str,
    *,
    user_id: str,
    token: str | None = None,
    repository: str | None = None,
) -> str:
    """Dispatch the dedicated GitHub Actions development workflow."""
    instruction = str(instruction or "").strip()
    if not instruction:
        return "開発指示が空です。『開発: ○○を実装して』の形式で指定してください。"

    if not _is_authorized_user(user_id):
        return "このLINEユーザーには開発ワークフローの実行権限がありません。"

    repository = repository or os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "開発ワークフローを起動できません。GITHUB_TOKENが設定されていません。"

    url = f"https://api.github.com/repos/{repository}/actions/workflows/{_WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": "main",
        "inputs": {
            "instruction": instruction,
            "user_id": str(user_id),
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
    except Exception as exc:
        return f"開発ワークフローの起動に失敗しました: {type(exc).__name__}"

    if response.status_code not in (200, 201, 202, 204):
        return f"開発ワークフローの起動に失敗しました (GitHub HTTP {response.status_code})。"

    return (
        "🚀 開発指示を受け付けました。\n"
        f"指示: {instruction}\n"
        "GitHub Actionsで開発・テストを開始しました。\n"
        "通常のLINE会話とは分離して実行します。"
    )
