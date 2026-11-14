"""Safety wiring tests for the manual-only distributed-loop consolidation."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _event_block(path):
    source = path.read_text(encoding="utf-8")
    return source.split("\non:\n", 1)[1].split("\npermissions:", 1)[0], source


def test_distributed_loop_is_manual_only_and_stays_fail_closed():
    events, source = _event_block(WORKFLOWS / "distributed-autonomous-loop.yml")
    assert "workflow_dispatch:" in events
    for forbidden in ("schedule:", "issue_comment:", "pull_request_target:", "push:"):
        assert forbidden not in events
    assert "execution_enabled == 'true' && false" in source
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in source
    assert "AUTO_APPLY_PATCH: 'false'" in source
    assert "AUTO_DEPLOY: 'false'" in source


def test_continuous_workflow_is_manual_only_and_has_no_recursive_dispatch():
    events, source = _event_block(WORKFLOWS / "continuous-distributed-loop.yml")
    assert "workflow_dispatch:" in events
    for forbidden in ("workflow_run:", "schedule:", "push:", "issue_comment:"):
        assert forbidden not in events
    assert "gh workflow run distributed-autonomous-loop.yml" not in source
    assert "actions: write" not in source
    assert "contents: write" not in source


def test_side_workflows_are_manual_only():
    names = (
        "hourly-self-improvement-sidecar.yml",
        "line-full-control-hourly.yml",
        "star-night-cloud-hourly.yml",
        "orca-phase1-read-only-observation.yml",
    )
    for name in names:
        events, _source = _event_block(WORKFLOWS / name)
        assert "workflow_dispatch:" in events, name
        for forbidden in ("schedule:", "push:", "workflow_run:", "issue_comment:"):
            assert forbidden not in events, name


def test_orca_observer_remains_read_only():
    _events, source = _event_block(WORKFLOWS / "orca-phase1-read-only-observation.yml")
    assert "execution_enabled" not in source or "execution_enabled: false" in source
    assert "Observe state without executing tasks" in source
    assert "permissions:" in source
    assert "contents: read" in source


def test_continuation_gate_stops_if_any_task_fails(tmp_path):
    from scripts.chain_job_ai import decide

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        json.dumps({
            "task_id": "task-one",
            "status": "FAIL",
            "exit_code": 1,
            "control_tower": {"recorded": True, "orchestration": {"allow_continue": True}},
        }),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        json.dumps({"completed": ["task-one"]}), encoding="utf-8"
    )
    result = decide(evidence, "continuation_depth=0", "success")
    assert result["continue"] is False
    assert result["reason"] == "task_status_not_verified_pass"


def test_continuation_gate_stops_when_task_is_not_run(tmp_path):
    from scripts.chain_job_ai import decide

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        json.dumps({
            "task_id": "queue-empty-task",
            "status": "NOT_RUN",
            "exit_code": 78,
            "control_tower": {"recorded": True, "orchestration": {"allow_continue": True}},
        }),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        json.dumps({"completed": []}), encoding="utf-8"
    )
    result = decide(evidence, "continuation_depth=0", "success")
    assert result["continue"] is False
    assert result["reason"] == "task_status_not_verified_pass"
