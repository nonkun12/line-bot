import distributed_loop_trigger as trigger
from distributed_loop_trigger import request_distributed_loop

def test_trigger_ignores_non_command(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "こんにちは")
    assert handled is False
    assert reply == ""

def test_trigger_recognizes_loop_command_aliases(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for command in ("分散ループ開始", "分散Loop開始", "分散AIループ開始", "分散AI Loop開始", "分散AI 回して"):
        handled, reply = request_distributed_loop("u1", command)
        assert handled is True
        assert "認証未設定" in reply

def test_trigger_denies_unknown_user(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u2", "分散ループ開始")
    assert handled is True
    assert "許可されていません" in reply

def test_trigger_requires_token(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = request_distributed_loop("u1", "分散ループ開始")
    assert handled is True
    assert "認証未設定" in reply

def test_bounded_loop_command_selects_requested_count(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = request_distributed_loop("u1", "分散ループを4回、安全確認付きで実行")
    assert handled is True
    assert "認証未設定" in reply

def test_bounded_loop_without_safety_confirmation_does_not_trigger(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "分散ループを4回")
    assert handled is False
    assert reply == ""

def test_invalid_loop_count_does_not_trigger(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "分散ループを5回、安全確認付きで実行")
    assert handled is False
    assert reply == ""


def test_natural_start_defaults_to_four_tasks():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散Loopを起動") == 4


def test_natural_start_variants_default_to_four_tasks():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散ループを起動") == 4
    assert _requested_max_tasks("分散AIループを起動") == 4


def test_legacy_start_remains_one_task():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散Loop開始") == 1


def test_bounded_command_respects_requested_count():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散Loopを2回、安全確認付きで実行") == 2


def test_more_than_four_tasks_is_rejected():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散Loopを5回、安全確認付きで実行") is None


def test_full_natural_four_task_command():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "分散Loopを起動。4タスクまで安全に実行し、"
        "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
        "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください。"
    )
    assert _requested_max_tasks(message) == 4


def test_full_natural_four_task_command_accepts_safety_confirmation_wording():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "分散Loopを起動。4タスクまで安全確認付きで実行し、"
        "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
        "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください。"
    )
    assert _requested_max_tasks(message) == 4


def test_full_natural_four_task_command_tolerates_line_transport_variants():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "\u200b分散Loopを起動。4タスクまで安全に実行し、\r\n"
        "各タスクをSafety Gate付きで確認。問題があれば即停止し、\n"
        "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください。\ufeff"
    )
    assert _requested_max_tasks(message) == 4


def test_bounded_command_keeps_four_task_cap_after_normalization():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks(" 分散Loopを4回、 安全確認付きで実行 ") == 4
    assert _requested_max_tasks("分散Loopを５回、安全確認付きで実行") is None


def test_full_natural_four_task_command_accepts_missing_terminal_period():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "分散Loopを起動。4タスクまで安全確認付きで実行し、"
        "各タスクをSafety Gate付きで確認。問題があれば即停止し、"
        "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください"
    )
    assert _requested_max_tasks(message) == 4


def test_full_natural_four_task_command_accepts_missing_terminal_period_with_transport_whitespace():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "\u200b分散Loopを起動。4タスクまで安全確認付きで実行し、\r\n"
        "各タスクをSafety Gate付きで確認。問題があれば即停止し、\n"
        "最後にTask ID / PASS・FAIL / SHA / 変更ファイル / 成果を報告してください\ufeff"
    )
    assert _requested_max_tasks(message) == 4


def test_similar_unapproved_natural_command_does_not_trigger():
    from distributed_loop_trigger import _requested_max_tasks

    message = (
        "分散Loopを起動。4タスクまで安全確認付きで実行し、"
        "問題があれば停止して、結果を報告してください"
    )
    assert _requested_max_tasks(message) is None


class _Response:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(
        self, runs, *, auto_create_run=True, created_status="in_progress",
        artifacts=None, artifact_zip=b"",
    ):
        self.runs = list(runs)
        self.auto_create_run = auto_create_run
        self.created_status = created_status
        self.artifacts = list(artifacts or [])
        self.artifact_zip = artifact_zip
        self.posted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        url = args[0] if args else ""
        params = kwargs.get("params", {})
        if url.endswith("/zip"):
            return _Response(200, content=self.artifact_zip)
        if url.endswith("/artifacts"):
            return _Response(200, {"artifacts": self.artifacts})
        if "status" in params:
            matching = [run for run in self.runs if run.get("status") == params["status"]]
            return _Response(200, {"workflow_runs": matching})
        if "event" in params:
            matching = [run for run in self.runs if run.get("event") == params["event"]]
            return _Response(200, {"workflow_runs": matching})
        if params.get("per_page") == 5:
            return _Response(200, {"workflow_runs": self.runs})
        return _Response(200, {"workflow_runs": self.runs})

    def post(self, *args, **kwargs):
        payload = kwargs.get("json") or {}
        self.posted.append(payload)
        if self.auto_create_run:
            request_id = payload["inputs"]["request_id"]
            self.runs.insert(0, {
                "id": 9001,
                "run_number": 86,
                "event": "workflow_dispatch",
                "status": self.created_status,
                "display_title": f"Distributed Loop request_id={request_id}",
                "created_at": "2099-01-01T00:00:00Z",
                "html_url": "https://github.com/nonkun12/line-bot/actions/runs/9001",
            })
        return _Response(204)


def test_dispatch_acknowledges_only_after_run_is_visible(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop(
            "u1", "分散Loopを4回、安全確認付きで実行"
        )
    assert handled is True
    assert "Run #86" in reply
    assert "4タスク" in reply
    inputs = client.posted[0]["inputs"]
    assert inputs["max_tasks"] == "4"
    assert len(inputs["request_id"]) == 32


def test_dispatch_reports_queued_request_as_accepted(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([], created_status="queued")
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "分散Loop開始")
    assert handled is True
    assert "待ち行列に登録しました" in reply
    assert "Run #86" in reply


def test_dispatch_does_not_claim_started_when_run_is_not_visible(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([], auto_create_run=False)
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        with patch.object(trigger.time, "monotonic", side_effect=[0, 21]):
            handled, reply = trigger.request_distributed_loop(
                "u1", "分散Loopを4回、安全確認付きで実行"
            )
    assert handled is True
    assert "この依頼に対応するRunを確認できませんでした" in reply
    assert "安全のため再送していません" in reply


def test_dispatch_rejects_when_running_and_waiting_slots_are_full(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([
        {"id": 1, "status": "in_progress"},
        {"id": 2, "status": "queued"},
    ])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "分散Loop開始")
    assert handled is True
    assert "受付枠（最大2件）が埋まっています" in reply
    assert client.posted == []


def test_dispatch_accepts_one_new_request_when_one_run_is_active(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{"id": 1, "status": "in_progress"}], created_status="queued")
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "分散Loop開始")
    assert handled is True
    assert "待ち行列に登録しました" in reply
    assert len(client.posted) == 1


def test_status_command_requires_allowlisted_user_and_token(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = request_distributed_loop("u1", "統括AIの状況")
    assert handled is True
    assert "GitHub認証未設定" in reply
    handled, reply = request_distributed_loop("u2", "統括AIの状況")
    assert handled is True
    assert "権限がありません" in reply


def test_status_command_reports_latest_runs(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 86,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "display_title": "test task",
        "head_sha": "a" * 40,
        "created_at": "2026-10-13T00:00:00Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/86",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "統括AIの状況")
    assert handled is True
    assert "Run #86" in reply
    assert "WORKFLOW_SUCCESS（タスクPASSは未確認）" in reply
    assert "a" * 12 in reply
    assert "実行Artifactを取得できず" in reply


def test_status_command_separates_skipped_runs_from_execution_history(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 88,
        "event": "issue_comment",
        "status": "completed",
        "conclusion": "skipped",
        "display_title": "comment did not match command",
        "head_sha": "d" * 40,
        "created_at": "2026-10-20T05:17:51Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/88",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "統括AIの状況")
    assert handled is True
    assert "実作業Runはまだ確認できません" in reply
    assert "起動条件不一致によるSKIPPED: 1件" in reply
    assert "Run #88" not in reply


def test_result_command_skips_non_matching_comment_runs(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 89,
        "event": "issue_comment",
        "status": "completed",
        "conclusion": "skipped",
        "display_title": "non-command comment",
        "head_sha": "e" * 40,
        "created_at": "2026-10-20T06:03:58Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/89",
    }, {
        "run_number": 88,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "display_title": "previous actual run",
        "head_sha": "f" * 40,
        "created_at": "2026-10-20T05:00:00Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/88",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "分散Loopの結果")
    assert handled is True
    assert "Run #88" in reply
    assert "起動条件不一致によるSKIPPED: 1件" in reply
    assert "Run #89" not in reply


def test_result_command_reports_latest_completed_run(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 87,
        "status": "in_progress",
        "display_title": "running",
        "head_sha": "b" * 40,
        "created_at": "2026-10-13T00:00:00Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/87",
    }, {
        "run_number": 86,
        "status": "completed",
        "conclusion": "failure",
        "display_title": "failed task",
        "head_sha": "c" * 40,
        "created_at": "2026-10-12T00:00:00Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/86",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "分散Loopの結果")
    assert handled is True
    assert "Run #86" in reply
    assert "FAIL（ワークフロー失敗）" in reply

def test_status_command_reports_only_skipped_runs_as_no_execution(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 496,
        "event": "issue_comment",
        "status": "completed",
        "conclusion": "skipped",
        "display_title": "unauthorized comment did not start loop",
        "head_sha": "d" * 40,
        "created_at": "2026-10-20T05:17:51Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/39374131870",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "統括AIの状況")
    assert handled is True
    assert "実行履歴から分離" in reply
    assert "起動条件不一致によるSKIPPED: 1件" in reply
    assert "Run #496" not in reply


def test_natural_distributed_ai_run_command_is_bounded_to_one_task():
    from distributed_loop_trigger import _requested_max_tasks

    assert _requested_max_tasks("分散AI 回して") == 1
    # LINE whitespace normalization allows transport spacing variants only.
    assert _requested_max_tasks("分散AI回して") == 1
    assert _requested_max_tasks("分散AI を回して") is None

def test_dispatch_counts_pending_and_waiting_runs_toward_capacity(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    for queued_status in ("pending", "waiting"):
        client = _Client([
            {"id": 1, "status": "in_progress"},
            {"id": 2, "status": queued_status},
        ])
        from unittest.mock import patch
        with patch.object(trigger.httpx, "Client", return_value=client):
            handled, reply = trigger.request_distributed_loop("u1", "分散Loop開始")
        assert handled is True
        assert "受付枠（最大2件）が埋まっています" in reply
        assert client.posted == []




def test_status_command_reads_task_result_and_hold_count_from_run_artifact(monkeypatch):
    import json
    from io import BytesIO
    from zipfile import ZipFile

    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "distributed-final-report.txt",
            "# 分散Loop 終了報告\n"
            "- 結果: **BLOCKED**\n"
            "- 結果理由: all_pending_tasks_held\n"
            "- 今回の実行タスク: 0/1\n"
            "- キュー進捗: 0/0\n",
        )
        archive.writestr(
            "autonomous-loop-refill-report.json",
            json.dumps({
                "eligible_catalog_count": 0,
                "skipped_catalog_held_ids": ["held-a", "held-b"],
            }),
        )
        archive.writestr(
            "minimal-autonomous-loop.jsonl",
            '{"status":"NOT_RUN","task_id":"","task_count":0}\n',
        )
    blob = output.getvalue()
    run = {
        "id": 123,
        "run_number": 91,
        "event": "schedule",
        "status": "completed",
        "conclusion": "success",
        "display_title": "scheduled loop",
        "head_sha": "a" * 40,
        "created_at": "2026-10-20T07:00:00Z",
        "html_url": "https://github.com/nonkun12/line-bot/actions/runs/123",
    }
    client = _Client(
        [run],
        artifacts=[{
            "id": 456,
            "name": "minimal-autonomous-loop-123",
            "expired": False,
            "size_in_bytes": len(blob),
        }],
        artifact_zip=blob,
    )
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop("u1", "統括AIの状況")
    assert handled is True
    assert "実タスク結果: BLOCKED（all_pending_tasks_held）" in reply
    assert "今回の実行タスク: 0/1" in reply
    assert "キュー進捗: 0/0" in reply
    assert "安全保留（Catalog）: 2件" in reply
    assert "Catalog実行候補: 0件" in reply
    assert "Task ID付き実行記録: 0件" in reply
