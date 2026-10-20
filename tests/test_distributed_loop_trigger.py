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
    for command in ("分散ループ開始", "分散Loop開始", "分散AIループ開始", "分散AI Loop開始"):
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
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, runs):
        self.runs = list(runs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        params = kwargs.get("params", {})
        if "event" in params or params.get("per_page") == 5:
            return _Response(200, {"workflow_runs": self.runs})
        return _Response(200, {"workflow_runs": []})

    def post(self, *args, **kwargs):
        return _Response(204)


def test_dispatch_acknowledges_only_after_run_is_visible(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([{
        "run_number": 86,
        "event": "workflow_dispatch",
        "created_at": "2099-01-01T00:00:00Z",
    }])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        handled, reply = trigger.request_distributed_loop(
            "u1", "分散Loopを4回、安全確認付きで実行"
        )
    assert handled is True
    assert "Run #86" in reply
    assert "4タスク" in reply


def test_dispatch_does_not_claim_started_when_run_is_not_visible(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "test-token")
    client = _Client([])
    from unittest.mock import patch
    with patch.object(trigger.httpx, "Client", return_value=client):
        with patch.object(trigger.time, "monotonic", side_effect=[0, 21]):
            handled, reply = trigger.request_distributed_loop(
                "u1", "分散Loopを4回、安全確認付きで実行"
            )
    assert handled is True
    assert "実行開始を確認できませんでした" in reply
    assert "安全のため再実行していません" in reply


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
    assert "success" in reply
    assert "a" * 12 in reply


def test_status_command_labels_skipped_as_not_run_and_shows_event(monkeypatch):
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
    assert "SKIPPED（起動条件不一致・タスク未実行）" in reply
    assert "イベント: issue_comment" in reply
    assert "Run #88" in reply


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
    assert "failure" in reply

def test_status_command_labels_skipped_runs_as_not_executed(monkeypatch):
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
    assert "SKIPPED（起動条件不一致・タスク未実行）" in reply
    assert "Run #496" in reply
    assert "PASS" not in reply
