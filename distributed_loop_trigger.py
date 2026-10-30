"""Safe LINE-triggered dispatcher for the distributed GitHub Actions loop."""
from __future__ import annotations

import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Tuple

import httpx

REPO = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
WORKFLOW = "distributed-autonomous-loop.yml"
TRIGGER_PHRASES = frozenset(
    {
        "分散ループ開始",
        "分散Loop開始",
        "分散AIループ開始",
        "分散AI Loop開始",
        "分散AI 回して",
        "distributed loop start",
        "分散ループを起動",
        "分散Loopを起動",
        "分散AIループを起動",
        "分散AI Loopを起動",
    }
)

# Explicit bounded commands must include an unambiguous safety confirmation.
_BOUNDED_TRIGGER_RE = re.compile(
    r"^(?:分散ループ|分散Loop|分散AIループ|分散AI Loop)を([1-4])回"
    r"、?安全確認付きで実行(?:してください)?$"
)

# Keep the natural 4-task command strict, but accept the exact phrasings
# used by the LINE secretary without broadening to arbitrary text.
_NATURAL_FOUR_TASK_TRIGGERS = frozenset(
    {
        (
            "分散Loopを起動。4タスクまで安全に実行し、"
            "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
            "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください。"
        ),
        (
            "分散Loopを起動。4タスクまで安全に実行し、"
            "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
            "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください"
        ),
        (
            "分散Loopを起動。4タスクまで安全確認付きで実行し、"
            "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
            "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください。"
        ),
        (
            "分散Loopを起動。4タスクまで安全確認付きで実行し、"
            "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
            "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください"
        ),
    }
)


def _normalize_command(message: str) -> str:
    """Normalize harmless LINE transport differences without broadening command tokens."""
    command = unicodedata.normalize("NFKC", str(message))
    command = re.sub(r"[\u200b-\u200d\ufeff]", "", command)
    return re.sub(r"\s+", "", command)


def _requested_max_tasks(message: str) -> int | None:
    command = _normalize_command(message)
    normalized_trigger_phrases = {_normalize_command(phrase) for phrase in TRIGGER_PHRASES}
    if command in normalized_trigger_phrases:
        return 4 if "起動" in command else 1

    if command in {_normalize_command(text) for text in _NATURAL_FOUR_TASK_TRIGGERS}:
        return 4

    normalized_bounded_pattern = re.compile(
        r"^(?:分散ループ|分散Loop|分散AIループ|分散AI Loop)を([1-4])回"
        r"、?安全確認付きで実行(?:してください)?$"
    )
    match = normalized_bounded_pattern.fullmatch(command)
    if match:
        return int(match.group(1))
    return None


def _allowed_users() -> set[str]:
    return {
        x.strip()
        for x in os.environ.get("DISTRIBUTED_LOOP_LINE_USER_IDS", "").split(",")
        if x.strip()
    }


def _display_run_state(run: dict[str, object]) -> str:
    """Describe workflow-level state without falsely claiming task PASS."""
    status = run.get("status")
    if status != "completed":
        return str(status or "unknown").upper()
    conclusion = run.get("conclusion")
    if not isinstance(conclusion, str):
        return "UNKNOWN"
    labels = {
        "success": "WORKFLOW_SUCCESS（タスクPASSは未確認）",
        "failure": "FAIL（ワークフロー失敗）",
        "skipped": "SKIPPED（起動条件不一致・タスク未実行）",
        "cancelled": "CANCELLED（中断）",
        "timed_out": "TIMEOUT",
        "action_required": "ACTION_REQUIRED",
        "neutral": "NEUTRAL（タスク結果未確定）",
        "stale": "STALE（結果未確定）",
        "startup_failure": "STARTUP_FAILURE",
    }
    return labels.get(conclusion, conclusion.upper())


def request_distributed_loop(user_id: str, message: str) -> Tuple[bool, str]:
    command = _normalize_command(message)
    status_kind = None
    if command in {"統括AIの状況", "統括AI状況", "分散Loopの状況", "分散ループの状況"}:
        status_kind = "status"
    elif command in {"分散Loopの結果", "分散ループの結果", "分散Loop結果", "分散ループ結果"}:
        status_kind = "result"

    max_tasks = _requested_max_tasks(message)
    if max_tasks is None and status_kind is None:
        return False, ""
    if not user_id or user_id not in _allowed_users():
        return True, "分散Loop起動は許可されていません（このLINEユーザーには統括AIの操作権限がありません）。"
    token = os.environ.get("GITHUB_ACTIONS_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return True, "統括AIを安全に操作できません（GitHub認証未設定）。"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{REPO}"
    try:
        with httpx.Client(timeout=8.0) as client:
            if status_kind is not None:
                response = client.get(
                    f"{base}/actions/workflows/{WORKFLOW}/runs",
                    params={"branch": "main", "per_page": 5},
                    headers=headers,
                )
                if response.status_code in {401, 403}:
                    return True, "統括AIの状態を取得できません（GitHub権限不足）。"
                response.raise_for_status()
                runs = response.json().get("workflow_runs", [])
                if not runs:
                    return True, "分散Loopの実行履歴はまだありません。"
                if status_kind == "result":
                    runs = [next((run for run in runs if run.get("status") == "completed"), runs[0])]
                lines = ["統括AI／分散Loop 状況" if status_kind == "status" else "分散Loop 最新結果"]
                for run in runs[:5 if status_kind == "status" else 1]:
                    number = run.get("run_number", "?")
                    state = _display_run_state(run)
                    event = str(run.get("event") or "unknown")
                    title = str(run.get("display_title") or "分散Loop")[:100]
                    sha = str(run.get("head_sha") or "")
                    created = str(run.get("created_at") or "")
                    url = str(run.get("html_url") or "")
                    lines.append(f"Run #{number}: {state} / {title}")
                    lines.append(f"イベント: {event}")
                    if created:
                        lines.append(f"開始: {created}")
                    if sha:
                        lines.append(f"SHA: {sha[:12]}")
                    if url.startswith("https://github.com/"):
                        lines.append(url)
                return True, "\n".join(lines)
            outstanding_runs: dict[str, dict] = {}
            for status in ("in_progress", "queued"):
                response = client.get(
                    f"{base}/actions/workflows/{WORKFLOW}/runs",
                    params={"branch": "main", "status": status, "per_page": 100},
                    headers=headers,
                )
                if response.status_code in {401, 403}:
                    return True, "分散Loopの待ち行列を確認できません（GitHub権限不足）。"
                response.raise_for_status()
                for run in response.json().get("workflow_runs", []):
                    run_id = run.get("id")
                    if run_id is not None:
                        outstanding_runs[str(run_id)] = run

            # Keep the LINE intake deliberately small: one running and one waiting
            # request at most. GitHub's queue:max is a backstop for other trusted
            # workflow triggers, not an invitation to build an unbounded backlog.
            if len(outstanding_runs) >= 2:
                return True, (
                    "分散Loopは実行中または待機中です。LINEからの受付枠（最大2件）が埋まっています。"
                    "現在の処理が進んでから、もう一度依頼してください。"
                )

            dispatch_started_at = datetime.now(timezone.utc).timestamp()
            request_id = uuid.uuid4().hex
            r = client.post(
                f"{base}/actions/workflows/{WORKFLOW}/dispatches",
                json={
                    "ref": "main",
                    "inputs": {
                        "max_tasks": str(max_tasks),
                        "request_id": request_id,
                    },
                },
                headers=headers,
            )
            if r.status_code == 204:
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    runs_response = client.get(
                        f"{base}/actions/workflows/{WORKFLOW}/runs",
                        params={"branch": "main", "event": "workflow_dispatch", "per_page": 100},
                        headers=headers,
                    )
                    runs_response.raise_for_status()
                    for run in runs_response.json().get("workflow_runs", []):
                        display_title = str(run.get("display_title") or "")
                        if request_id not in display_title:
                            continue
                        created_at = run.get("created_at")
                        if not isinstance(created_at, str) or not created_at:
                            continue
                        try:
                            created_ts = datetime.fromisoformat(
                                created_at.replace("Z", "+00:00")
                            ).timestamp()
                        except ValueError:
                            continue
                        if created_ts < dispatch_started_at - 5:
                            continue

                        run_number = run.get("run_number", "?")
                        status = run.get("status")
                        url = str(run.get("html_url") or "")
                        link = f"\\n{url}" if url.startswith("https://github.com/") else ""
                        if status == "queued":
                            return True, (
                                f"分散Loopの依頼を受け付け、待ち行列に登録しました。Run #{run_number} / "
                                f"最大{max_tasks}タスクです。{link}"
                            )
                        if status == "in_progress":
                            return True, (
                                f"分散Loopを起動しました。Run #{run_number} / "
                                f"最大{max_tasks}タスクまで安全に実行します。{link}"
                            )
                        return True, (
                            f"分散Loopの受付を確認しました。Run #{run_number} / "
                            f"状態: {_display_run_state(run)}{link}"
                        )
                    time.sleep(1.0)
                return True, (
                    "分散Loop起動要求はGitHubに受理されましたが、"
                    "この依頼に対応するRunを確認できませんでした。安全のため再送していません。"
                )
            if r.status_code in {401, 403}:
                return True, "分散Loopを起動できません（GitHub Actions権限不足）。"
            return True, f"分散Loop起動に失敗しました（GitHub HTTP {r.status_code}）。"
    except httpx.HTTPError:
        return True, "統括AIへの接続に失敗しました（GitHub通信エラー）。"
