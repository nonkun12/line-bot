"""Authenticated LINE command for explicit Recovery AI resume-review acknowledgement."""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Tuple

import httpx

WORKFLOW = "recovery-ai-resume-review.yml"
_COMMAND_RE = re.compile(
    r"^RecoveryAI再開レビュー確認task_id=([A-Za-z0-9._-]{1,100})reviewed=true$",
    re.IGNORECASE,
)


def _normalize(message: str) -> str:
    command = unicodedata.normalize("NFKC", str(message))
    command = re.sub(r"[\u200b-\u200d\ufeff]", "", command)
    return re.sub(r"\s+", "", command)


def request_recovery_resume_review(user_id: str, message: str) -> Tuple[bool, str]:
    """Dispatch a state-only review acknowledgement; never runs a task itself."""
    command = _normalize(message)
    prefix = "RecoveryAI再開レビュー確認"
    if not command.startswith(prefix):
        return False, ""
    match = _COMMAND_RE.fullmatch(command)
    if not match:
        return True, (
            "形式が正しくありません。"
            "Recovery AI再開レビュー確認 task_id=TASK_ID reviewed=true"
        )
    task_id = match.group(1)
    allowed = {
        item.strip()
        for item in os.environ.get("DISTRIBUTED_LOOP_LINE_USER_IDS", "").split(",")
        if item.strip()
    }
    if not user_id or user_id not in allowed:
        return True, "Recovery AIの操作は許可されていません。"
    token = os.environ.get("GITHUB_ACTIONS_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return True, "Recovery AIの確認を送信できません（GitHub認証未設定）。"

    repo = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                json={"ref": "main", "inputs": {"task_id": task_id}},
                headers=headers,
            )
        if response.status_code == 204:
            return True, (
                f"Recovery AIの再開レビュー確認を受け付けました（{task_id}）。"
                "状態更新の検証が完了するまで、タスクは実行されません。"
            )
        if response.status_code in {401, 403}:
            return True, "Recovery AIの確認を送信できません（GitHub権限不足）。"
        return True, f"Recovery AIの確認に失敗しました（GitHub HTTP {response.status_code}）。"
    except httpx.HTTPError:
        return True, "Recovery AIへの接続に失敗しました（GitHub通信エラー）。"
