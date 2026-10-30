import json

import pytest

from scripts.maintenance_ai import build_report, _load_rows


def test_failed_runtime_task_is_triaged_without_authorizing_repair():
    report = build_report([{
        "task_id": "sample-regression-task",
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
        "recovery_ai": {"decision": {"action": "HOLD", "requires_human": True}},
    }])

    assert report["agent"] == "MaintenanceAI"
    assert report["status"] == "REVIEW_REQUIRED"
    diagnosis = report["diagnoses"][0]
    assert diagnosis["category"] == "recovery_hold"
    assert diagnosis["requires_human"] is True
    assert all(value is False for value in diagnosis["permissions"].values())


def test_runtime_failure_without_recovery_hold_requests_log_review():
    report = build_report([{
        "task_id": "runtime-failure",
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
    }])

    diagnosis = report["diagnoses"][0]
    assert diagnosis["category"] == "task_runtime_failure"
    assert "workflow job log" in diagnosis["recommendation"]


def test_safety_gate_failure_is_never_retried_automatically():
    report = build_report([{
        "task_id": "rea-blocked",
        "status": "FAIL",
        "rea": {"gate": "BLOCKED"},
    }])

    diagnosis = report["diagnoses"][0]
    assert diagnosis["category"] == "safety_gate_blocked"
    assert diagnosis["permissions"]["retry_task"] is False
    assert diagnosis["permissions"]["clear_hold"] is False


def test_passed_task_needs_no_maintenance_action():
    report = build_report([{"task_id": "passed-task", "status": "PASS"}])
    assert report["status"] == "NO_ACTION"
    assert report["diagnoses"][0]["category"] == "completed"


def test_empty_evidence_fails_closed():
    report = build_report([])
    assert report["status"] == "NO_TASK_EVIDENCE"
    assert report["diagnoses"] == []


def test_task_id_and_free_text_are_not_reflected_in_report():
    report = build_report([{
        "task_id": "../../secret",
        "status": "FAIL",
        "failure_reason": "raw-token=do-not-echo",
        "exception": "private exception content",
    }])
    encoded = json.dumps(report)
    assert "../../secret" not in encoded
    assert "do-not-echo" not in encoded
    assert "private exception content" not in encoded


def test_jsonl_loader_rejects_non_object_records(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        _load_rows(path)
