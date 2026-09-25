from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scripts.check_autonomous_loop_watchdog import expected_slot, find_scheduled_run


def test_expected_slot_selects_latest_completed_jst_slot():
    now = datetime(2026, 9, 23, 7, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now).hour == 3
    assert expected_slot(now).minute == 5


def test_expected_slot_selects_afternoon_slot():
    now = datetime(2026, 9, 23, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now).hour == 15
    assert expected_slot(now).minute == 5


def test_find_scheduled_run_uses_workflow_scoped_schedule_endpoint(monkeypatch):
    scheduled = {
        "name": "Autonomous Development Loop",
        "event": "schedule",
        "id": 123,
        "created_at": "2026-09-22T18:07:00Z",
        "status": "completed",
        "conclusion": "failure",
    }
    captured = {}
    def fake_github_json(url):
        captured["url"] = url
        return {
            "workflow_runs": [
                {"name": "other", "event": "schedule", "id": 1, "created_at": "2026-09-23T18:05:00Z"},
                {"name": "Autonomous Development Loop", "event": "workflow_dispatch", "id": 2, "created_at": "2026-09-23T18:06:00Z"},
                scheduled,
            ]
        }

    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        fake_github_json,
    )

    slot = datetime(2026, 9, 24, 3, 5, tzinfo=ZoneInfo("Asia/Tokyo"))
    # The expected slot is 2026-09-23 03:05 JST, so the example above is outside it.
    assert find_scheduled_run("nonkun12/line-bot", slot) is None
    assert captured["url"].endswith(
        "/actions/workflows/nightly-autonomous-worker.yml/runs?event=schedule&per_page=20"
    )

    slot = datetime(2026, 9, 24, 3, 5, tzinfo=ZoneInfo("Asia/Tokyo")) - __import__("datetime").timedelta(days=1)
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


def test_find_scheduled_run_accepts_small_scheduler_delay(monkeypatch):
    scheduled = {
        "name": "Autonomous Development Loop",
        "event": "schedule",
        "id": 456,
        "created_at": "2026-09-22T18:11:00Z",
        "status": "completed",
        "conclusion": "success",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [scheduled]},
    )
    slot = datetime(2026, 9, 23, 3, 5, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


def test_watchdog_bootstraps_repo_root_for_direct_execution():
    source = __import__("pathlib").Path("scripts/check_autonomous_loop_watchdog.py").read_text(encoding="utf-8")
    assert "ROOT = Path(__file__).resolve().parents[1]" in source
    assert "sys.path.insert(0, str(ROOT))" in source
