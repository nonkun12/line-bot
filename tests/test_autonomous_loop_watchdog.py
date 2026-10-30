from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agents.sheets.autonomous_ledger import HEADERS
from scripts.check_autonomous_loop_watchdog import (
    audit_row_outcome,
    expected_slot,
    find_scheduled_run,
    has_audit_row,
    run_is_pending_within_grace,
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


def test_find_scheduled_run_accepts_workflow_run_name_override(monkeypatch):
    scheduled = {
        "name": "Distributed Loop (continuation_depth=0)",
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
                {"name": "Other Workflow", "event": "schedule", "id": 1, "created_at": "2026-09-23T19:30:00Z"},
                {"name": "Distributed Loop (continuation_depth=0)", "event": "workflow_dispatch", "id": 2, "created_at": "2026-09-23T19:31:00Z"},
                scheduled,
            ]
        }

    monkeypatch.setattr("scripts.check_autonomous_loop_watchdog.github_json", fake_github_json)

    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled
    assert captured["url"].endswith(
        "/actions/workflows/distributed-autonomous-loop.yml/runs?event=schedule&per_page=20"
    )

def test_find_scheduled_run_accepts_delayed_run_within_four_hours(monkeypatch):
    scheduled = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 789,
        "created_at": "2026-09-22T22:26:00Z",
        "status": "completed",
        "conclusion": "failure",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [scheduled]},
    )
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) == scheduled


def test_find_scheduled_run_rejects_run_after_four_hour_window(monkeypatch):
    too_late = {
        "name": "Distributed Autonomous Development Loop",
        "event": "schedule",
        "id": 790,
        "created_at": "2026-09-22T23:31:00Z",
        "status": "completed",
        "conclusion": "success",
    }
    monkeypatch.setattr(
        "scripts.check_autonomous_loop_watchdog.github_json",
        lambda _url: {"workflow_runs": [too_late]},
    )
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert find_scheduled_run("nonkun12/line-bot", slot) is None


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
        self.read_ranges = []

    def sheet_titles(self):
        return ["AutonomousDevelopment"]

    def read_rows(self, range_name):
        self.read_ranges.append(range_name)
        return self.rows


def _audit_row(**overrides):
    values = {name: "" for name in HEADERS}
    values.update({
        "timestamp": "2026-10-16T00:00:00Z",
        "run_id": "12345",
        "task_id": "task-example",
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "tests_result": "PASS",
        "verification_result": "PASS",
        "safety_gate_result": "PASS",
        "blocked_failed_reason": "",
    })
    values.update(overrides)
    return [values[name] for name in HEADERS]


def test_has_audit_row_uses_run_id_header_column_not_column_a():
    row = ["2026-10-09T00:00:00Z", "37861561986", "task-a"] + [""] * (len(HEADERS) - 3)
    client = FakeSheetsClient([HEADERS, row])
    assert has_audit_row(client, "37861561986")
    assert not has_audit_row(client, "missing-run")


def test_has_audit_row_supports_ledger_starting_in_later_column():
    header = ["", "", ""] + HEADERS
    row = ["", "", "", "2026-10-09T00:00:00Z", "37861561986", "task-a"] + [""] * (len(HEADERS) - 3)
    client = FakeSheetsClient([header, row])
    assert has_audit_row(client, "37861561986")


def test_audit_row_outcome_finds_run_after_row_1000():
    filler = [[""] * len(HEADERS) for _ in range(1000)]
    client = FakeSheetsClient([HEADERS, *filler, _audit_row()])
    assert audit_row_outcome(client, "12345") == (True, "verified_task_passed")
    assert client.read_ranges == ["'AutonomousDevelopment'!A:ZZ"]

def test_audit_row_outcome_accepts_verified_pass():
    client = FakeSheetsClient([HEADERS, _audit_row()])
    assert audit_row_outcome(client, "12345") == (True, "verified_task_passed")


def test_audit_row_outcome_rejects_queue_empty_even_when_workflow_succeeded():
    client = FakeSheetsClient([HEADERS, _audit_row(
        task_id="NOT_RUN",
        safety_gate_result="BLOCKED",
        verification_result="NOT_RUN",
        tests_result="NOT_RUN",
        blocked_failed_reason="queue_empty",
    )])
    ok, reason = audit_row_outcome(client, "12345")
    assert not ok
    assert "did not execute a valid task" in reason


def test_audit_row_outcome_rejects_missing_safety_gate_pass():
    client = FakeSheetsClient([HEADERS, _audit_row(safety_gate_result="BLOCKED")])
    ok, reason = audit_row_outcome(client, "12345")
    assert not ok
    assert "did not pass Safety Gate" in reason


def test_audit_row_outcome_rejects_duplicate_run_rows():
    client = FakeSheetsClient([HEADERS, _audit_row(), _audit_row()])
    ok, reason = audit_row_outcome(client, "12345")
    assert not ok
    assert "Ambiguous Sheets audit rows" in reason


def test_audit_row_outcome_rejects_empty_or_skipped_tests():
    for value in ("", "SKIPPED", "NOT_RUN", "FAIL"):
        ok, reason = audit_row_outcome(FakeSheetsClient([HEADERS, _audit_row(tests_result=value)]), "12345")
        assert not ok
        assert "tests are not successful" in reason


def test_audit_row_outcome_rejects_malformed_task_id():
    for value in ("queue-empty", "bad task id", "../task"):
        ok, reason = audit_row_outcome(FakeSheetsClient([HEADERS, _audit_row(task_id=value)]), "12345")
        assert not ok
        assert "valid task" in reason


def test_audit_row_outcome_requires_valid_base_and_produced_shas():
    valid = "a" * 40
    for field in ("base_sha", "produced_sha"):
        for value in ("", "1234", "g" * 40):
            row_values = {"base_sha": valid, "produced_sha": valid}
            row_values[field] = value
            ok, reason = audit_row_outcome(FakeSheetsClient([HEADERS, _audit_row(**row_values)]), "12345")
            assert not ok
            assert "SHA is missing or malformed" in reason


def test_audit_row_outcome_accepts_no_change_with_valid_shas():
    sha = "b" * 40
    client = FakeSheetsClient([HEADERS, _audit_row(tests_result="NO_CHANGE", verification_result="NO_CHANGE", base_sha=sha, produced_sha=sha)])
    assert audit_row_outcome(client, "12345") == (True, "verified_task_passed")


def test_active_run_is_pending_inside_90_minute_grace():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(minutes=30)
    for status in ("queued", "in_progress"):
        assert run_is_pending_within_grace({"status": status}, slot, now)


def test_queued_run_remains_pending_during_bounded_queue_grace():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(hours=3)
    assert run_is_pending_within_grace({"status": "queued"}, slot, now)


def test_queued_run_is_not_pending_after_bounded_queue_grace():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(minutes=361)
    assert not run_is_pending_within_grace({"status": "queued"}, slot, now)


def test_in_progress_run_uses_actual_start_time_after_slot_delay():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(hours=3)
    started = now - timedelta(minutes=30)
    run = {"status": "in_progress", "run_started_at": started.isoformat()}
    assert run_is_pending_within_grace(run, slot, now)


def test_in_progress_run_fails_after_90_minutes_from_actual_start():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(hours=3)
    started = now - timedelta(minutes=91)
    run = {"status": "in_progress", "run_started_at": started.isoformat()}
    assert not run_is_pending_within_grace(run, slot, now)


def test_completed_run_is_never_classified_as_pending():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert not run_is_pending_within_grace({"status": "completed"}, slot, slot)


def test_missing_scheduled_run_is_pending_within_90_minute_grace():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    for minutes in (0, 30, 90):
        now = slot + timedelta(minutes=minutes)
        assert run_is_pending_within_grace(None, slot, now)


def test_missing_scheduled_run_remains_pending_through_discovery_window():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    for minutes in (0, 30, 90, 239, 240):
        now = slot + timedelta(minutes=minutes)
        assert run_is_pending_within_grace(None, slot, now)


def test_missing_scheduled_run_is_not_pending_after_discovery_window():
    slot = datetime(2026, 9, 23, 4, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = slot + timedelta(minutes=241)
    assert not run_is_pending_within_grace(None, slot, now)
