"""Safe LINE-triggered dispatcher for the distributed GitHub Actions loop."""
from __future__ import annotations
import os
from typing import Tuple
import httpx

REPO = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
WORKFLOW = "distributed-autonomous-loop.yml"
TRIGGER_PHRASES = frozenset({"分散ループ開始", "分散AIループ開始", "distributed loop start"})

def _allowed_users() -> set[str]:
    return {x.strip() for x in os.environ.get("DISTRIBUTED_LOOP_LINE_USER_IDS", "").split(",") if x.strip()}

def request_distributed_loop(user_id: str, message: str) -> Tuple[bool, str]:
    if str(message).strip() not in TRIGGER_PHRASES:
        return False, ""
    if not user_id or user_id not in _allowed_users():
        return True, "分散Loop起動は許可されていません。"
    token = os.environ.get("GITHUB_ACTIONS_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return True, "分散Loop起動を安全に実行できません（GitHub認証未設定）。"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    base = f"https://api.github.com/repos/{REPO}"
    try:
        with httpx.Client(timeout=8.0) as client:
            for status in ("in_progress", "queued"):
                r = client.get(f"{base}/actions/workflows/{WORKFLOW}/runs",
                               params={"branch":"main","status":status,"per_page":1}, headers=headers)
                r.raise_for_status()
                if r.json().get("workflow_runs", []):
                    return True, "分散Loopはすでに実行中です。重複起動はしません。"
            r = client.post(f"{base}/actions/workflows/{WORKFLOW}/dispatches",
                            json={"ref":"main","inputs":{"max_tasks":"1"}}, headers=headers)
            if r.status_code == 204:
                return True, "分散Loopを起動しました。1タスク限定で安全に実行します。"
            if r.status_code in {401,403}:
                return True, "分散Loopを起動できません（GitHub Actions権限不足）。"
            return True, f"分散Loop起動に失敗しました（GitHub HTTP {r.status_code}）。"
    except httpx.HTTPError:
        return True, "分散Loop起動に失敗しました（GitHub通信エラー）。"
