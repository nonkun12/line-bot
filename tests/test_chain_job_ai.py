from __future__ import annotations

import json
from pathlib import Path

from scripts.chain_job_ai import decide


def _evidence(tmp_path: Path, rows, completed=None):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "minimal-autonomous-loop.jsonl").write_text(
        "".join(json.dumps(row) + "\\n" for row in rows), encoding="utf-8"
    )
    (root / "autonomous-loop-state.json").write_text(
        json.dumps({"completed": completed if completed is not None else [r["task_id"] for r in rows]}),
        encoding="utf-8",
    )
    return root


def _row(task_id="task-one", *, status="PASS", exit_code=0, recorded=True, allowed=True):
    return {
        "task_id": task_id,
        "status": status,
        "exit_code": exit_code,
        "control_tower": {
            "recorded": recorded,
            "orchestration": {"allow_continue": allowed},
        },
    }


def test_chain_job_ai_continues_only_after_full_verified_evidence(tmp_path):
    evidence = _evidence(tmp_path, [_row()])
    result = decide(evidence, "Distributed Loop (continuation_depth=2)", "success")
    assert result["decision"] == "CONTINUE"
    assert result["next_depth"] == 3
    assert result["verified_task_ids"] == ["task-one"]
    assert result["permissions"]["execute_task"] is False
    assert result["permissions"]["clear_hold"] is False


def test_chain_job_ai_stops_on_no_change_to_prevent_no_progress_chain(tmp_path):
    evidence = _evidence(tmp_path, [_row(status="NO_CHANGE")])
    result = decide(evidence, "Distributed Loop (continuation_depth=0)", "success")
    assert result["reason"] == "task_status_not_verified_pass"


def test_chain_job_ai_stops_on_blocked_or_failed_task(tmp_path):
    evidence = _evidence(tmp_path, [_row(status="BLOCKED", exit_code=79)])
    result = decide(evidence, "Distributed Loop (continuation_depth=0)", "success")
    assert result["reason"] == "task_status_not_verified_pass"


def test_chain_job_ai_requires_control_tower_approval(tmp_path):
    evidence = _evidence(tmp_path, [_row(allowed=False)])
    result = decide(evidence, "Distributed Loop (continuation_depth=0)", "success")
    assert result["reason"] == "control_tower_denied_continue"


def test_chain_job_ai_requires_durable_completion(tmp_path):
    evidence = _evidence(tmp_path, [_row()], completed=[])
    result = decide(evidence, "Distributed Loop (continuation_depth=0)", "success")
    assert result["reason"] == "durable_completion_not_confirmed"


def test_chain_job_ai_stops_at_depth_limit(tmp_path):
    evidence = _evidence(tmp_path, [_row()])
    result = decide(evidence, "Distributed Loop (continuation_depth=12)", "success")
    assert result["reason"] == "bounded_depth_limit"


def test_chain_job_ai_honors_kill_switch_and_missing_evidence(tmp_path):
    assert decide(tmp_path, "continuation_depth=0", "success", kill_switch="true")["reason"] == "kill_switch_enabled"
    assert decide(tmp_path, "continuation_depth=0", "success", evidence_download_outcome="failure")["reason"] == "missing_or_unreadable_artifact"


def test_chain_job_ai_rejects_ambiguous_artifacts(tmp_path):
    evidence = _evidence(tmp_path, [_row()])
    duplicate = evidence / "nested"
    duplicate.mkdir()
    (duplicate / "minimal-autonomous-loop.jsonl").write_text(json.dumps(_row()) + "\\n")
    result = decide(evidence, "continuation_depth=0", "success")
    assert result["reason"] == "missing_or_ambiguous_evidence"
