from __future__ import annotations

from scripts.self_improvement_hourly_report import build_report
from scripts.self_improvement_state import sanitize_records


def test_hourly_report_is_read_only_and_reports_recurring_failures():
    records = sanitize_records([
        {"kind": "failure", "task_id": "task-a", "detail": "raw failure text"},
        {"kind": "failure", "task_id": "task-b", "detail": "different raw text"},
        {"kind": "repair", "task_id": "task-c", "detail": "raw repair text"},
        {"record_type": "cycle_memory", "outcome": "FAIL"},
    ])
    report = build_report({"self_improvement_history": records})

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["evidence"]["failure_signals"] == 2
    assert report["evidence"]["cycle_outcomes"]["FAIL"] == 1
    assert report["recurring_patterns"]
    assert report["review_candidates"]
    assert report["safety"] == {
        "read_only": True,
        "queue_mutated": False,
        "approval_changed": False,
        "source_modified": False,
        "merge_or_deploy": False,
        "human_review_required": True,
    }


def test_hourly_report_handles_empty_history_without_inventing_work():
    report = build_report({"self_improvement_history": []})

    assert report["status"] == "NO_RECURRING_SIGNAL"
    assert report["evidence"]["history_records"] == 0
    assert report["review_candidates"] == []
    assert report["recurring_patterns"] == []


def test_hourly_report_fails_closed_on_invalid_durable_history():
    try:
        build_report({"self_improvement_history": [{"kind": "failure", "detail": "untrusted"}]})
    except ValueError as exc:
        assert "schema is invalid" in str(exc)
    else:
        raise AssertionError("invalid durable history must be rejected")
