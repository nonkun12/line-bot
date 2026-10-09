from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.check_autonomous_loop_watchdog import expected_slot, find_scheduled_run


def test_expected_slot_selects_latest_completed_jst_slot():
    now = datetime(2026, 9, 23, 5, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now).hour == 4
    assert expected_slot(now).minute == 30


def test_expected_slot_selects_afternoon_slot():
    now = datetime(2026, 9, 23, 17, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert expected_slot(now).hour == 16
    assert expected_slot(now).minute == 30


def test_expected_slot_before_first_window_uses_previous_day_last_window():
    now = datetime(2026, 9, 23, 3, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    slot = expected_slot(now)
    assert slot.date().day == 22
    assert (slot.hour, slot.minute) == (22, 30)


def test_find_scheduled_run_uses_workflow_scoped_schedule_endpoint(monkeypatch):
    scheduled = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 123,
        "created_at": "2026-09-22T19:37:00Z",
        "status": "completed",
        "conclusion": "failure",
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

    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        fake_github_json,
    )

    slot = datetime(2026, 9, 24, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) is None
    assert captured["url"].endswith(
        "/actions/workflows/distributed-autonomous-loop.yml/runs?event=schedule&per_page=20"
    )

    slot -= timedelta(days=1)
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


def test_find_scheduled_run_accepts_small_scheduler_delay(monkeypatch):
    scheduled = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 456,
        "created_at": "2026-09-22T19:35:00Z",
        "status": "completed",
        "conclusion": "success",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [scheduled]},
    )
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


def test_find_scheduled_run_rejects_a_different_slot_on_the_same_day(monkeypatch):
    run = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 789,
        "created_at": "2026-09-23T01:30:00Z",  # 10:30 JST, not 04:30 JST
        "status": "completed",
        "conclusion": "success",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [run]},
    )
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) is None


def test_find_ledger_record_uses_run_id_column_beside_shifted_headers():
    from agents.sheets.autonomous_ledger import HEADERS
    from scripts.check_autonomous_loop_watchdog import find_ledger_record

    class Client:
        def sheet_titles(self):
            return ["AutonomousDevelopment"]

        def read_rows(self, _range):
            row = [""] * 30 + [
                "2026-09-22T19:40:00+00:00", "123", "", "distributed-loop",
                "agent", "summary", "", "", "", "", "NO_TASKS", "NO_TASKS",
                "NOT_APPLICABLE", "NOT_AUTO_MERGED", "", "review_queue_for_new_candidate",
                "RECORDED",
            ]
            return [[""] * 30 + HEADERS, row]

    tab, record = find_ledger_record(Client(), "123")
    assert tab == "AutonomousDevelopment"
    assert record["run_id"] == "123"
    assert record["tests_result"] == "NO_TASKS"


def test_find_ledger_record_returns_missing_run_after_valid_headers():
    from agents.sheets.autonomous_ledger import HEADERS
    from scripts.check_autonomous_loop_watchdog import find_ledger_record

    class Client:
        def sheet_titles(self):
            return ["AutonomousDevelopment"]

        def read_rows(self, _range):
            return [[""] * 30 + HEADERS]

    tab, record = find_ledger_record(Client(), "missing-run")
    assert tab == "AutonomousDevelopment"
    assert record is None


def test_find_ledger_record_fails_closed_for_wrong_tab():
    import pytest

    from scripts.check_autonomous_loop_watchdog import find_ledger_record

    class Client:
        def sheet_titles(self):
            return ["OtherTab"]

    with pytest.raises(RuntimeError, match="not found"):
        find_ledger_record(Client(), "123")


def test_find_ledger_record_fails_closed_when_tab_has_no_header():
    import pytest

    from scripts.check_autonomous_loop_watchdog import find_ledger_record

    class Client:
        def sheet_titles(self):
            return ["AutonomousDevelopment"]

        def read_rows(self, _range):
            return []

    with pytest.raises(RuntimeError, match="are missing"):
        find_ledger_record(Client(), "123")
