from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.check_autonomous_loop_watchdog import (
    expected_slot,
    find_scheduled_run,
    has_audit_row,
)


def test_expected_slot_selects_latest_completed_jst_slot():
    now = datetime(2026, 9, 23, 7, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now) == datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_expected_slot_selects_evening_slot():
    now = datetime(2026, 9, 23, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now) == datetime(2026, 9, 23, 16, 30, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_expected_slot_rolls_back_to_previous_day_before_first_slot():
    now = datetime(2026, 9, 23, 3, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now) == datetime(2026, 9, 22, 22, 30, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_find_scheduled_run_uses_distributed_workflow_and_schedule_event(monkeypatch):
    scheduled = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 123,
        "created_at": "2026-09-22T19:31:00Z",
        "status": "completed",
        "conclusion": "success",
    }
    captured = {}

    def fake_github_json(url):
        captured["url"] = url
        return {
            "workflow_runs": [
                {"name": "other", "event": "schedule", "id": 1, "created_at": "2026-09-23T19:30:00Z"},
                {"name": "Distributed Autonomous Development Loop", "event": "workflow_dispatch", "id": 2, "created_at": "2026-09-23T19:31:00Z"},
                scheduled,
            ]
        }

    monkeypatch.setattr("scripts.check_autonomous_loop_watchdog.github_json", fake_github_json)

    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled
    assert captured["url"].endswith(
        "/actions/workflows/distributed-autonomous-loop.yml/runs?event=schedule&per_page=20"
    )


def test_find_scheduled_run_accepts_small_scheduler_delay(monkeypatch):
    scheduled = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 456,
        "created_at": "2026-09-22T19:41:00Z",
        "status": "completed",
        "conclusion": "success",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [scheduled]},
    )
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


class FakeSheetsClient:
    def __init__(self, rows):
        self.rows = rows

    def sheet_titles(self):
        return ["AutonomousDevelopment"]

    def read_rows(self, _range):
        return self.rows


def test_has_audit_row_uses_run_id_header_column_not_column_a():
    from agents.sheets.autonomous_ledger import HEADERS

    row = ["2026-10-09T00:00:00Z", "37861561986", "task-a"] + [""] * (len(HEADERS) - 3)
    client = FakeSheetsClient([HEADERS, row])
    assert has_audit_row(client, "37861561986")
    assert not has_audit_row(client, "missing-run")


def test_has_audit_row_supports_ledger_starting_in_later_column():
    from agents.sheets.autonomous_ledger import HEADERS

    header = ["", "", ""] + HEADERS
    row = ["", "", "", "2026-10-09T00:00:00Z", "37861561986", "task-a"] + [""] * (len(HEADERS) - 3)
    client = FakeSheetsClient([header, row])
    assert has_audit_row(client, "37861561986")
