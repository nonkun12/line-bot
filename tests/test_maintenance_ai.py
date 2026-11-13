import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.maintenance_ai import build_report, _load_rows


def test_failed_runtime_task_is_triaged_without_authorizing_repair():
    report = build_report([{"task_id":"sample-regression-task","status":"FAIL","failure_reason":"task_runtime_failed","recovery_ai":{"decision":{"action":"HOLD","requires_human":True}}}])
    assert report["agent"] == "MaintenanceAI"
    assert report["status"] == "REVIEW_REQUIRED"
    diagnosis = report["diagnoses"][0]
    assert diagnosis["category"] == "recovery_hold"
    assert diagnosis["requires_human"] is True
    assert all(value is False for value in diagnosis["permissions"].values())


def test_runtime_failure_without_recovery_hold_requests_log_review():
    diagnosis = build_report([{"task_id":"runtime-failure","status":"FAIL","failure_reason":"task_runtime_failed"}])["diagnoses"][0]
    assert diagnosis["category"] == "task_runtime_failure"
    assert "workflow job log" in diagnosis["recommendation"]


def test_safety_gate_failure_is_never_retried_automatically():
    diagnosis = build_report([{"task_id":"rea-blocked","status":"FAIL","rea":{"gate":"BLOCKED"}}])["diagnoses"][0]
    assert diagnosis["category"] == "safety_gate_blocked"
    assert diagnosis["permissions"]["retry_task"] is False
    assert diagnosis["permissions"]["clear_hold"] is False


def test_passed_task_needs_no_maintenance_action():
    report = build_report([{"task_id":"passed-task","status":"PASS"}])
    assert report["status"] == "NO_ACTION"
    assert report["diagnoses"][0]["category"] == "completed"


def test_empty_evidence_fails_closed():
    report = build_report([])
    assert report["status"] == "NO_TASK_EVIDENCE"
    assert report["diagnoses"] == []


def test_task_id_and_free_text_are_not_reflected_in_report():
    report = build_report([{"task_id":"../../secret","status":"FAIL","failure_reason":"raw-token=do-not-echo","exception":"private exception content"}])
    encoded = json.dumps(report)
    assert "../../secret" not in encoded
    assert "do-not-echo" not in encoded
    assert "private exception content" not in encoded


def test_jsonl_loader_rejects_non_object_records(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(["not","an","object"]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        _load_rows(path)


@pytest.mark.parametrize("row", [
    {"task_id":"empty-queue","status":"NOT_RUN","failure_reason":"queue_empty"},
    {"task_id":"empty-queue-reason","status":"UNKNOWN","failure_reason":"queue_empty"},
])
def test_empty_queue_is_classified_as_queue_exhausted(row):
    diagnosis = build_report([row])["diagnoses"][0]
    assert diagnosis["category"] == "queue_exhausted"
    assert diagnosis["status"] in {"NOT_RUN","UNKNOWN"}
    assert diagnosis["requires_human"] is True
    assert diagnosis["permissions"]["retry_task"] is False


def test_all_pending_tasks_held_is_distinguished_from_empty_queue():
    diagnosis = build_report([{"task_id":"held-queue","status":"BLOCKED","failure_reason":"all_pending_tasks_held"}])["diagnoses"][0]
    assert diagnosis["category"] == "all_tasks_held"


def test_rea_blocked_overrides_contradictory_pass():
    diagnosis = build_report([{"task_id":"contradictory","status":"PASS","rea":{"gate":"BLOCKED"}}])["diagnoses"][0]
    assert diagnosis["category"] == "safety_gate_blocked"
    assert diagnosis["requires_human"] is True


def test_recovery_hold_overrides_contradictory_pass():
    diagnosis = build_report([{"task_id":"contradictory-hold","status":"PASS","recovery_ai":{"decision":{"action":"HOLD","requires_human":True}}}])["diagnoses"][0]
    assert diagnosis["category"] == "recovery_hold"
    assert diagnosis["requires_human"] is True


@pytest.mark.parametrize("bad_value", [[], {}, 7, None])
def test_untrusted_status_and_reason_types_do_not_crash(bad_value):
    report = build_report([{"task_id":"malformed","status":bad_value,"failure_reason":bad_value,"recovery_ai":{"decision":{"action":bad_value}}}])
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["diagnoses"][0]["category"] == "insufficient_evidence"



def test_empty_jsonl_with_not_run_marker_is_reported_as_queue_exhausted(tmp_path):
    from scripts.maintenance_ai import _read_queue_state

    marker = tmp_path / "not-run"
    marker.write_text("queue_empty\n", encoding="utf-8")
    state = _read_queue_state(marker, None)
    report = build_report([], queue_state=state)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["diagnoses"][0]["category"] == "queue_exhausted"
    assert report["diagnoses"][0]["permissions"]["retry_task"] is False


@pytest.mark.parametrize(("marker_text", "expected"), [
    ("all_pending_tasks_held\n", "all_tasks_held"),
    ("catalog_exhausted_held:3\n", "all_tasks_held"),
    ("catalog_exhausted_review_pending:2\n", "review_pending"),
    ("catalog_exhausted_mixed:held=2,review=1\n", "mixed_queue_blocked"),
])
def test_held_and_review_markers_are_classified_without_raw_text(tmp_path, marker_text, expected):
    from scripts.maintenance_ai import _read_queue_state

    marker = tmp_path / "held"
    marker.write_text(marker_text, encoding="utf-8")
    state = _read_queue_state(None, marker)
    report = build_report([], queue_state=state)
    diagnosis = report["diagnoses"][0]
    assert diagnosis["category"] == expected
    assert diagnosis["requires_human"] is True
    assert all(value is False for value in diagnosis["permissions"].values())


def test_unknown_queue_marker_fails_closed_without_echoing_content(tmp_path):
    from scripts.maintenance_ai import _read_queue_state

    marker = tmp_path / "held"
    marker.write_text("secret-token=must-not-appear", encoding="utf-8")
    with pytest.raises(ValueError, match="not allowlisted"):
        _read_queue_state(None, marker)


def test_conflicting_queue_markers_fail_closed(tmp_path):
    from scripts.maintenance_ai import _read_queue_state

    not_run = tmp_path / "not-run"
    held = tmp_path / "held"
    not_run.write_text("queue_empty\n", encoding="utf-8")
    held.write_text("all_pending_tasks_held\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting"):
        _read_queue_state(not_run, held)


def test_known_failure_code_explains_append_only_repair_failure_without_retry_authority():
    diagnosis = build_report([{
        "task_id": "review-coverage-gap-example",
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
        "failure_code": "existing_test_modified_repair_failed",
        "recovery_ai": {"decision": {"action": "HOLD", "requires_human": True}},
    }])["diagnoses"][0]
    assert diagnosis["category"] == "test_plan_repair_failed"
    assert diagnosis["failure_code"] == "existing_test_modified_repair_failed"
    assert "append one new test only" in diagnosis["recommendation"]
    assert diagnosis["permissions"]["retry_task"] is False
    assert diagnosis["permissions"]["clear_hold"] is False


def test_maintenance_ai_cli_bootstraps_project_imports_without_pythonpath(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "maintenance_ai.py"
    results = tmp_path / "results.jsonl"
    output = tmp_path / "diagnosis.json"
    results.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(script), "--results", str(results), "--output", str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "NO_TASK_EVIDENCE"


def test_invalid_change_count_failure_code_is_classified_without_retry_authority():
    diagnosis = build_report([{
        "task_id": "invalid-change-count-example",
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
        "failure_code": "invalid_change_count",
        "recovery_ai": {"decision": {"action": "HOLD", "requires_human": True}},
    }])["diagnoses"][0]
    assert diagnosis["category"] == "invalid_plan_change_count"
    assert diagnosis["failure_code"] == "invalid_change_count"
    assert diagnosis["permissions"]["retry_task"] is False
    assert diagnosis["permissions"]["clear_hold"] is False

@pytest.mark.parametrize("failure_code", [None, [], {}, 7])
def test_present_malformed_failure_code_is_invalid_evidence(failure_code):
    diagnosis = build_report([{
        "task_id": "malformed-failure-code",
        "status": "PASS",
        "failure_code": failure_code,
    }])["diagnoses"][0]
    assert diagnosis["category"] == "invalid_failure_code_evidence"
    assert diagnosis["requires_human"] is True
    assert diagnosis["permissions"]["retry_task"] is False


def test_absent_failure_code_does_not_create_invalid_evidence():
    diagnosis = build_report([{
        "task_id": "no-failure-code",
        "status": "PASS",
    }])["diagnoses"][0]
    assert diagnosis["category"] == "completed"
    assert diagnosis["requires_human"] is False


def test_distributed_loop_writes_real_newlines_to_held_marker():
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"
    text = workflow.read_text(encoding="utf-8")
    assert text.count('write_text(reason + chr(10), encoding="utf-8")') >= 2
    assert 'write_text(reason + "\\\\n", encoding="utf-8")' not in text
