"""Regression tests for the embedded continuation evidence gate.

These execute the exact Python heredoc embedded in the workflow, rather than
reimplementing the gate in a separate test-only function.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "continuous-distributed-loop.yml"
)


def _gate_script():
    source = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"          python - <<'PY'\n(.*?)\n          PY",
        source,
        flags=re.DOTALL,
    )
    assert match, "continuation gate Python heredoc must exist"
    return textwrap.dedent(match.group(1))


def _run_gate(tmp_path, rows, completed):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        json.dumps({"completed": completed}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(output)
    result = subprocess.run(
        [sys.executable, "-c", _gate_script()],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.exists() else ""


def _row(task_id, *, status="PASS", exit_code=0):
    return {"task_id": task_id, "status": status, "exit_code": exit_code}


def test_continuation_gate_accepts_one_verified_pass(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-one")], ["task-one"]
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=true", "task_id=task-one"]
    assert "CONTINUATION_ALLOWED verified_tasks=1" in result.stdout


def test_continuation_gate_accepts_verified_no_change(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-no-change", status="NO_CHANGE")], ["task-no-change"]
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=true", "task_id=task-no-change"]
    assert "CONTINUATION_ALLOWED verified_tasks=1" in result.stdout


def test_continuation_gate_accepts_four_verified_passes(tmp_path):
    ids = ["task-one", "task-two", "task-three", "task-four"]
    result, output = _run_gate(
        tmp_path, [_row(task_id) for task_id in ids], ids
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=true", "task_id=task-four"]
    assert "CONTINUATION_ALLOWED verified_tasks=4" in result.stdout


def test_continuation_gate_stops_if_any_task_fails(tmp_path):
    rows = [_row("task-one"), _row("task-two", status="FAIL")]
    result, output = _run_gate(tmp_path, rows, ["task-one", "task-two"])
    assert result.returncode == 0
    assert "continue=false" in output.splitlines()
    assert "CONTINUATION_STOP=task_status_not_successful" in result.stdout


def test_continuation_gate_rejects_boolean_exit_code(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-one", exit_code=True)], ["task-one"]
    )
    assert result.returncode == 0
    assert "continue=false" in output
    assert "CONTINUATION_STOP=task_exit_code_not_zero" in result.stdout


def test_continuation_gate_requires_every_durable_completion(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-one"), _row("task-two")], ["task-one"]
    )
    assert result.returncode == 0
    assert "continue=false" in output
    assert "CONTINUATION_STOP=durable_completion_not_confirmed" in result.stdout


def test_continuation_gate_rejects_duplicate_task_ids(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-one"), _row("task-one")], ["task-one"]
    )
    assert result.returncode == 0
    assert "continue=false" in output
    assert "CONTINUATION_STOP=duplicate_task_ids" in result.stdout


def test_continuation_gate_rejects_more_than_four_results(tmp_path):
    ids = [f"task-{index}" for index in range(5)]
    result, output = _run_gate(
        tmp_path, [_row(task_id) for task_id in ids], ids
    )
    assert result.returncode == 0
    assert "continue=false" in output
    assert "CONTINUATION_STOP=unexpected_task_result_count" in result.stdout



def test_continuation_gate_rejects_empty_result_file(tmp_path):
    result, output = _run_gate(tmp_path, [], [])
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=unexpected_task_result_count" in result.stdout


def test_continuation_gate_rejects_non_object_row(tmp_path):
    result, output = _run_gate(tmp_path, ["not-an-object"], [])
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=invalid_task_result_row" in result.stdout


def test_continuation_gate_rejects_invalid_task_id(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("../unsafe")], ["../unsafe"]
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=missing_or_invalid_task_id" in result.stdout


def test_continuation_gate_rejects_malformed_durable_state(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        json.dumps(_row("task-one")) + "\n", encoding="utf-8"
    )
    (evidence / "autonomous-loop-state.json").write_text(
        json.dumps({"completed": "task-one"}), encoding="utf-8"
    )
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(output)
    result = subprocess.run(
        [sys.executable, "-c", _gate_script()],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert output.read_text(encoding="utf-8").splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=durable_completion_not_confirmed" in result.stdout


def test_distributed_loop_continuation_depth_is_bounded_and_propagated():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    source = (root / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    continuation = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")

    assert "run-name: Distributed Loop (continuation_depth=${{ inputs.continuation_depth || '0' }})" in source
    assert "continuation_depth:" in source
    assert "options:" in source
    assert 'match = re.search(r"continuation_depth=(\\d+)", title)' in continuation
    assert 'if [ "$depth" -ge 3 ]; then' in continuation
    assert '-f continuation_depth="${{ steps.active.outputs.next_depth }}"' in continuation
    assert "CONTINUATION_STOP=bounded_depth_limit" in continuation
    # The bounded chain must have a scheduled fallback, so a depth cap is not
    # a permanent manual-resume requirement.
    scheduled = (root / "nightly-autonomous-worker.yml").read_text(encoding="utf-8")
    assert "cron: '0 4 * * *'" in scheduled
    assert "cron: '0 16 * * *'" in scheduled
    assert "cron: '0 22 * * *'" in scheduled
    assert "timezone: 'Asia/Tokyo'" in scheduled


def test_distributed_loop_continuation_still_requires_existing_evidence_gate():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    continuation = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")

    assert "steps.gate.outputs.continue == 'true'" in continuation
    assert "steps.active.outputs.dispatch == 'true'" in continuation
    assert "durable_completion_not_confirmed" in continuation
    assert "task_status_not_successful" in continuation
    assert "another_loop_is_active" in continuation
