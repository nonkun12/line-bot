"""Safe LINE-triggered dispatcher for the distributed GitHub Actions loop."""
from __future__ import annotations

import io
import json
import os
import re
import time
import unicodedata
import uuid
import zipfile
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


def _read_artifact_member(archive: zipfile.ZipFile, filename: str, max_bytes: int) -> bytes | None:
    matches = [
        info for info in archive.infolist()
        if not info.is_dir() and info.filename.rsplit("/", 1)[-1] == filename
    ]
    if len(matches) != 1 or matches[0].file_size > max_bytes:
        return None
    return archive.read(matches[0])


def _load_run_task_evidence(
    client: httpx.Client,
    base: str,
    headers: dict[str, str],
    run: dict[str, object],
) -> dict[str, object] | None:
    """Read only the bounded, run-scoped evidence artifact; never infer task PASS."""
    run_id = run.get("id")
    if isinstance(run_id, bool) or not str(run_id or "").isdigit():
        return None

    try:
        response = client.get(
            f"{base}/actions/runs/{run_id}/artifacts",
            params={"per_page": 100},
            headers=headers,
        )
        if response.status_code in {401, 403}:
            return None
        response.raise_for_status()
        artifact_payload = response.json()
        if not isinstance(artifact_payload, dict):
            return None
        artifacts = artifact_payload.get("artifacts", [])
        expected_name = f"minimal-autonomous-loop-{run_id}"
        artifact = next(
            (
                item for item in artifacts
                if isinstance(item, dict)
                and item.get("name") == expected_name
                and item.get("expired") is not True
            ),
            None,
        )
        if artifact is None:
            return None

        size = artifact.get("size_in_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > 5 * 1024 * 1024
        ):
            return None
        artifact_id = artifact.get("id")
        if isinstance(artifact_id, bool) or not str(artifact_id or "").isdigit():
            return None

        download = client.get(
            f"{base}/actions/artifacts/{artifact_id}/zip",
            headers=headers,
            follow_redirects=True,
        )
        if download.status_code in {401, 403}:
            return None
        download.raise_for_status()
        blob = download.content
        if len(blob) > 5 * 1024 * 1024 or not zipfile.is_zipfile(io.BytesIO(blob)):
            return None

        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            report_bytes = _read_artifact_member(
                archive, "distributed-final-report.txt", 16 * 1024
            )
            refill_bytes = _read_artifact_member(
                archive, "autonomous-loop-refill-report.json", 256 * 1024
            )
            results_bytes = _read_artifact_member(
                archive, "minimal-autonomous-loop.jsonl", 64 * 1024
            )

        report = report_bytes.decode("utf-8") if report_bytes is not None else ""
        refill = json.loads(refill_bytes) if refill_bytes is not None else {}
        if not isinstance(refill, dict):
            refill = {}
        result_rows: list[dict[str, object]] = []
        if results_bytes is not None:
            for line in results_bytes.decode("utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    result_rows.append(item)

        def _report_int(pattern: str) -> int | None:
            match = re.search(pattern, report, re.MULTILINE)
            return int(match.group(1)) if match else None

        outcome_match = re.search(
            r"^- 結果:\s*\*\*([A-Z_]+)\*\*",
            report,
            re.MULTILINE,
        )
        reason_match = re.search(
            r"^- 結果理由:\s*([A-Za-z0-9_.:-]+)",
            report,
            re.MULTILINE,
        )
        held_ids = refill.get("skipped_catalog_held_ids")
        held_count = (
            len({item for item in held_ids if isinstance(item, str) and item})
            if isinstance(held_ids, list)
            else None
        )
        eligible_count = refill.get("eligible_catalog_count")
        if isinstance(eligible_count, bool) or not isinstance(eligible_count, int) or eligible_count < 0:
            eligible_count = None

        task_statuses: dict[str, int] = {}
        for item in result_rows:
            task_id = item.get("task_id")
            status = item.get("status")
            if isinstance(task_id, str) and task_id.strip() and isinstance(status, str):
                task_statuses[status] = task_statuses.get(status, 0) + 1

        return {
            "outcome": outcome_match.group(1) if outcome_match else None,
            "reason": reason_match.group(1) if reason_match else None,
            "attempted": _report_int(r"^- 今回の実行タスク:\s*(\d+)\s*/"),
            "requested": _report_int(r"^- 今回の実行タスク:\s*\d+\s*/\s*(\d+)"),
            "queue_completed": _report_int(r"^- キュー進捗:\s*(\d+)\s*/"),
            "queue_total": _report_int(r"^- キュー進捗:\s*\d+\s*/\s*(\d+)"),
            "held_count": held_count,
            "eligible_count": eligible_count,
            "task_statuses": task_statuses,
        }
    except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError):
        return None


def _append_task_evidence(
    lines: list[str],
    client: httpx.Client,
    base: str,
    headers: dict[str, str],
    run: dict[str, object],
) -> None:
    run_number = run.get("run_number", "?")
    if run.get("status") != "completed":
        lines.extend([
            f"【タスク実行結果／保留件数】Run #{run_number}",
            "実行中のため、タスク結果と保留件数は未確定です。",
        ])
        return

    evidence = _load_run_task_evidence(client, base, headers, run)
    lines.append(f"【タスク実行結果／保留件数】Run #{run_number}")
    if evidence is None:
        lines.append("実行Artifactを取得できず、タスク結果・保留件数は未確認です。")
        return

    outcome = evidence.get("outcome")
    reason = evidence.get("reason")
    if isinstance(outcome, str):
        suffix = f"（{reason}）" if isinstance(reason, str) else ""
        lines.append(f"実タスク結果: {outcome}{suffix}")
    else:
        lines.append("実タスク結果: Artifact内に結果行がなく未確認です。")

    attempted = evidence.get("attempted")
    requested = evidence.get("requested")
    if isinstance(attempted, int) and isinstance(requested, int):
        lines.append(f"今回の実行タスク: {attempted}/{requested}")

    queue_completed = evidence.get("queue_completed")
    queue_total = evidence.get("queue_total")
    if isinstance(queue_completed, int) and isinstance(queue_total, int):
        lines.append(f"キュー進捗: {queue_completed}/{queue_total}")

    task_statuses = evidence.get("task_statuses")
    if isinstance(task_statuses, dict) and task_statuses:
        detail = " / ".join(
            f"{status} {count}件" for status, count in sorted(task_statuses.items())
        )
        lines.append(f"Task ID付き実行記録: {detail}")
    elif attempted == 0:
        lines.append("Task ID付き実行記録: 0件")

    held_count = evidence.get("held_count")
    eligible_count = evidence.get("eligible_count")
    if isinstance(held_count, int):
        lines.append(f"安全保留（Catalog）: {held_count}件")
    else:
        lines.append("安全保留（Catalog）: 未取得")
    if isinstance(eligible_count, int):
        lines.append(f"Catalog実行候補: {eligible_count}件")


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
                    params={"branch": "main", "per_page": 100},
                    headers=headers,
                )
                if response.status_code in {401, 403}:
                    return True, "統括AIの状態を取得できません（GitHub権限不足）。"
                response.raise_for_status()
                run_payload = response.json()
                if not isinstance(run_payload, dict):
                    return True, "統括AIの状態を取得できません（GitHub応答形式が不正です）。"
                all_runs = run_payload.get("workflow_runs", [])
                if not isinstance(all_runs, list):
                    return True, "統括AIの状態を取得できません（GitHub応答形式が不正です）。"

                skipped_runs = [
                    run for run in all_runs
                    if isinstance(run, dict)
                    and run.get("status") == "completed"
                    and run.get("conclusion") == "skipped"
                ]
                execution_runs = [
                    run for run in all_runs
                    if isinstance(run, dict)
                    and not (
                        run.get("status") == "completed"
                        and run.get("conclusion") == "skipped"
                    )
                ]
                lines = [
                    "統括AI／分散Loop 状況"
                    if status_kind == "status"
                    else "分散Loop 最新結果"
                ]
                lines.append("【実際の実行履歴】")
                if not execution_runs:
                    lines.append("実作業Runはまだ確認できません。")
                else:
                    if status_kind == "result":
                        completed_runs = [
                            run for run in execution_runs
                            if run.get("status") == "completed"
                        ]
                        selected_runs = completed_runs[:1] or execution_runs[:1]
                    else:
                        selected_runs = execution_runs[:5]
                    for run in selected_runs:
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

                lines.append(
                    f"起動条件不一致によるSKIPPED: {len(skipped_runs)}件"
                    f"（直近{len(all_runs)}件中。実行履歴から分離）"
                )

                completed_actual_runs = [
                    run for run in execution_runs
                    if run.get("status") == "completed"
                ]
                evidence_run = completed_actual_runs[0] if completed_actual_runs else (
                    execution_runs[0] if execution_runs else None
                )
                if evidence_run is not None:
                    _append_task_evidence(lines, client, base, headers, evidence_run)
                else:
                    lines.extend([
                        "【タスク実行結果／保留件数】",
                        "対象となる実行Runがないため、タスク結果・保留件数は未取得です。",
                    ])
                return True, "\n".join(lines)
            outstanding_runs: dict[str, dict] = {}
            for status in ("in_progress", "queued", "pending", "waiting"):
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
                        link = f"\n{url}" if url.startswith("https://github.com/") else ""
                        if status in {"queued", "pending", "waiting"}:
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
