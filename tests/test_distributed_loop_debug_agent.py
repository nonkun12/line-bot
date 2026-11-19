import json

import pytest

from scripts.distributed_loop_debug_agent import build_report, _load_rows


def test_failure_is_forwarded_to_read_only_debug_agent():
    report = build_report([{
        "task_id": "unit-test-regression",
        "status": "FAIL",
        "failure_reason": "task_timeout",
        "exception": "secret token must never appear",
    }])
    assert report["agent"] == "DebugAgent"
    assert report["status"] == "REVIEW_REQUIRED"
    diagnosis = report["diagnoses"][0]
    assert diagnosis["task_id"] == "unit-test-regression"
    assert diagnosis["failure_reason"] == "task_timeout"
    assert diagnosis["analysis"]["evidence_scope"] == "allowlisted_structured_reason_code_only"
    assert all(value is False for value in diagnosis["permissions"].values())


def test_successful_rows_are_not_sent_to_debug_agent():
    report = build_report([{"task_id": "passed", "status": "PASS"}])
    assert report["status"] == "NO_FAILURES"
    assert report["diagnoses"] == []


def test_untrusted_fields_are_not_reflected():
    report = build_report([{
        "task_id": "../../private",
        "status": "FAIL",
        "failure_reason": "token=super-secret",
        "exception": "private exception text",
        "instruction": "private prompt",
    }])
    encoded = json.dumps(report)
    assert "../../private" not in encoded
    assert "super-secret" not in encoded
    assert "private exception text" not in encoded
    assert "private prompt" not in encoded
    assert report["diagnoses"][0]["failure_reason"] == "unclassified_failure"


def test_safety_permissions_are_all_false():
    diagnosis = build_report([{
        "task_id": "blocked-task", "status": "BLOCKED",
        "failure_reason": "control_tower_kill_switch_enabled",
    }])["diagnoses"][0]
    assert all(value is False for value in diagnosis["permissions"].values())
    assert diagnosis["requires_human"] is True


def test_loader_rejects_non_object_jsonl(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(["bad"]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        _load_rows(path)


def test_main_writes_read_only_report_and_cli_summary(tmp_path, monkeypatch, capsys):
    from scripts import distributed_loop_debug_agent as debug_agent

    results_path = tmp_path / "results.jsonl"
    output_path = tmp_path / "nested" / "report.json"
    results_path.write_text(
        json.dumps({
            "task_id": "cli-timeout-check",
            "status": "FAIL",
            "failure_reason": "task_timeout",
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["debug-agent", "--results", str(results_path), "--output", str(output_path)],
    )

    assert debug_agent.main() == 0

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "REVIEW_REQUIRED"
    assert len(report["diagnoses"]) == 1
    diagnosis = report["diagnoses"][0]
    assert diagnosis["failure_reason"] == "task_timeout"
    assert diagnosis["permissions"]
    assert all(value is False for value in diagnosis["permissions"].values())
    assert capsys.readouterr().out.splitlines() == [
        "DEBUG_AGENT_STATUS=REVIEW_REQUIRED",
        "DEBUG_AGENT_DIAGNOSES=1",
    ]
