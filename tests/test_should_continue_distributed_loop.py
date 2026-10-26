import json

from scripts.should_continue_distributed_loop import decide


def _row(status="PASS", exit_code=0, *, recorded=True, allow_continue=True, failure_reason=None):
    row = {
        "status": status,
        "exit_code": exit_code,
        "control_tower": {
            "recorded": recorded,
            "orchestration": {"allow_continue": allow_continue},
        },
    }
    if failure_reason:
        row["failure_reason"] = failure_reason
    return row


def _artifact(tmp_path, rows):
    path = tmp_path / "download" / "minimal-autonomous-loop.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path.parent


def test_continues_only_after_verified_pass(tmp_path):
    artifact = _artifact(tmp_path, [_row()])
    result = decide(artifact, "Distributed Loop (continuation_depth=1)", "success")
    assert result == {
        "continue": True,
        "reason": "verified_pass",
        "depth": 1,
        "next_depth": 2,
    }


def test_stops_when_depth_limit_reached(tmp_path):
    artifact = _artifact(tmp_path, [_row()])
    assert decide(artifact, "Distributed Loop (continuation_depth=3)", "success")["continue"] is False


def test_stops_for_queue_empty_or_missing_task_evidence(tmp_path):
    assert decide(tmp_path, "Distributed Loop (continuation_depth=0)", "success")["reason"] == "task_evidence_missing"


def test_stops_for_failed_or_blocked_task(tmp_path):
    artifact = _artifact(tmp_path, [_row("BLOCKED", 79)])
    assert decide(artifact, "Distributed Loop (continuation_depth=0)", "success")["reason"] == "task_not_pass"


def test_stops_when_control_tower_did_not_authorize_continuation(tmp_path):
    artifact = _artifact(tmp_path, [_row(allow_continue=False)])
    assert decide(artifact, "Distributed Loop (continuation_depth=0)", "success")["reason"] == "control_tower_denied_continue"


def test_stops_when_control_tower_evidence_missing(tmp_path):
    artifact = _artifact(tmp_path, [_row(recorded=False)])
    assert decide(artifact, "Distributed Loop (continuation_depth=0)", "success")["reason"] == "control_tower_evidence_missing"


def test_stops_when_source_workflow_failed_even_if_result_says_pass(tmp_path):
    artifact = _artifact(tmp_path, [_row()])
    assert decide(artifact, "Distributed Loop (continuation_depth=0)", "failure")["reason"] == "source_run_not_success"
