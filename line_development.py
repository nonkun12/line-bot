"""Explicit LINE/Slack -> governed development command dispatcher."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import httpx

from core.task_routing import TaskClassifier, TaskMode

_DEV_PREFIX = re.compile(r"^(?:/dev|開発|dev)\s*:?\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
_MAX_INSTRUCTION_LENGTH = 2000
_WORKFLOW_FILE = "line-development-dispatch.yml"
_DISPATCH_TIMEOUT_SECONDS = 10.0
_DISPATCH_ATTEMPTS = 3
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# LINE自動開発E2E本線確認
# LINE自動開発E2E最終確認
# LINE自動開発E2E再テスト
# LINE自動開発テスト


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
    authorized: bool = False,
) -> str:
    """Dispatch governed Secretary development or independent app creation."""
    instruction = str(instruction or "").strip()
    if not instruction:
        return "開発指示が空です。『開発: ○○を実装して』の形式で指定してください。"

    if not authorized and not _is_authorized_user(user_id):
        return "このユーザーには開発ワークフローの実行権限がありません。"

    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "開発ワークフローを起動できません。GITHUB_TOKENが設定されていません。"

    classification = TaskClassifier().classify(f"開発: {instruction}")
    if classification.mode == TaskMode.NEW_SOFTWARE:
        return (
            "新規アプリ作成は通常の開発経路と分離しています。"
            "『アプリ開発: ○○を作って』と明示してください。"
        )

    repository = repository or os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    dispatch_url = (
        f"https://api.github.com/repos/{repository}"
        f"/actions/workflows/{_WORKFLOW_FILE}/dispatches"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": "main",
        "inputs": {
            "instruction": instruction,
            "user_id": str(user_id),
        },
    }

    last_error: str | None = None
    for attempt in range(1, _DISPATCH_ATTEMPTS + 1):
        try:
            response = httpx.post(
                dispatch_url,
                json=payload,
                headers=headers,
                timeout=_DISPATCH_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = type(exc).__name__
            if attempt < _DISPATCH_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            return f"開発ワークフローの起動に失敗しました: {last_error}"
        except Exception as exc:
            return f"開発ワークフローの起動に失敗しました: {type(exc).__name__}"

        if response.status_code == 204:
            return "🚀 開発指示を受け付けました。GitHub Actionsで開発・テストを開始しました。\n通常のLINE会話とは分離して実行します。"

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _DISPATCH_ATTEMPTS:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(float(retry_after), 3.0) if retry_after else 0.5 * attempt
            except ValueError:
                delay = 0.5 * attempt
            time.sleep(max(delay, 0.1))
            continue

        detail = response.text.strip().replace("\n", " ")
        if len(detail) > 300:
            detail = detail[:300]
        if response.status_code in {401, 403}:
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（GitHub Token/権限を確認してください）"
        if detail:
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（{detail}）"
        return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}"

    return f"開発ワークフローの起動に失敗しました: {last_error or 'unknown error'}"
