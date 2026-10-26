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
    return {
        "task_id": task_id,
        "status": status,
        "exit_code": exit_code,
        "control_tower": {
            "recorded": True,
            "orchestration": {"allow_continue": True},
        },
    }


def test_continuation_gate_accepts_one_verified_pass(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-one")], ["task-one"]
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=true", "task_id=task-one"]
    assert "CONTINUATION_ALLOWED verified_tasks=1" in result.stdout


def test_continuation_gate_rejects_no_change(tmp_path):
    result, output = _run_gate(
        tmp_path, [_row("task-no-change", status="NO_CHANGE")], ["task-no-change"]
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=task_status_not_successful" in result.stdout


def test_continuation_gate_rejects_missing_control_tower_evidence(tmp_path):
    row = _row("task-one")
    row.pop("control_tower")
    result, output = _run_gate(tmp_path, [row], ["task-one"])
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=control_tower_evidence_missing" in result.stdout


def test_continuation_gate_rejects_control_tower_denial(tmp_path):
    row = _row("task-one")
    row["control_tower"]["orchestration"]["allow_continue"] = False
    result, output = _run_gate(tmp_path, [row], ["task-one"])
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=control_tower_denied_continue" in result.stdout


def test_continuation_gate_rejects_failure_reason_even_with_pass(tmp_path):
    row = _row("task-one")
    row["failure_reason"] = "unexpected warning"
    result, output = _run_gate(tmp_path, [row], ["task-one"])
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
    assert "CONTINUATION_STOP=failure_reason_present" in result.stdout


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


def test_continuation_gate_stops_when_task_is_not_run(tmp_path):
    result, output = _run_gate(
        tmp_path,
        [{"task_id": "", "status": "NOT_RUN", "exit_code": 78}],
        [],
    )
    assert result.returncode == 0
    assert output.splitlines() == ["continue=false"]
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


def test_distributed_loop_continuation_depth_is_propagated():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    source = (root / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    continuation = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")

    assert "run-name: Distributed Loop (continuation_depth=${{ inputs.continuation_depth || '0' }})" in source
    assert "continuation_depth:" in source
    assert "options:" in source
    assert 'match = re.search(r"continuation_depth=(\\d+)", title)' in continuation
    assert 'if [ "$depth" -ge 3 ]; then' not in continuation
    assert '-f continuation_depth="${{ steps.active.outputs.next_depth }}"' in continuation
    assert "CONTINUATION_STOP=bounded_depth_limit" not in continuation
    # The bounded chain resumes through the distributed loop's own schedule.
    scheduled = source
    assert "cron: '30 4,10,16,22 * * *'" in scheduled
    assert "timezone: 'Asia/Tokyo'" in scheduled
    assert "AUTO_APPLY_PATCH: 'false'" in source
    assert "AUTO_DEPLOY: 'false'" in source


def test_distributed_loop_continuation_still_requires_existing_evidence_gate():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    continuation = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")

    assert "steps.gate.outputs.continue == 'true'" in continuation
    assert "steps.active.outputs.dispatch == 'true'" in continuation
    assert "durable_completion_not_confirmed" in continuation
    assert "task_status_not_successful" in continuation
    assert "another_loop_is_active" in continuation
    assert "runs?status=queued&per_page=100" in continuation
    assert "runs?status=in_progress&per_page=100" in continuation



def _continuation_active_script():
    source = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"      - name: Avoid duplicate dispatch while another loop is queued or running\n"
        r"        id: active\n.*?\n        run: \|\n(.*?)(?=\n      - name: Dispatch the next bounded loop)",
        source,
        flags=re.DOTALL,
    )
    assert match, "continuation depth/active check step must exist"
    return textwrap.dedent(match.group(1))


def _run_active_check(tmp_path, title, *, active_count=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{active_count}'\n", encoding="utf-8")
    gh.chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env["RUN_DISPLAY_TITLE"] = title
    env["REPOSITORY"] = "nonkun12/line-bot"
    env["GITHUB_OUTPUT"] = str(output)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["bash", "-c", _continuation_active_script()],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.exists() else ""


def test_continuation_depth_zero_dispatches_depth_one(tmp_path):
    result, output = _run_active_check(tmp_path, "Distributed Loop (continuation_depth=0)")
    assert result.returncode == 0, result.stderr
    assert "dispatch=true" in output.splitlines()
    assert "next_depth=1" in output.splitlines()


def test_continuation_depth_two_dispatches_depth_three(tmp_path):
    result, output = _run_active_check(tmp_path, "Distributed Loop (continuation_depth=2)")
    assert result.returncode == 0, result.stderr
    assert "dispatch=true" in output.splitlines()
    assert "next_depth=3" in output.splitlines()


def test_continuation_depth_beyond_three_continues_when_no_active_run(tmp_path):
    result, output = _run_active_check(tmp_path, "Distributed Loop (continuation_depth=37)")
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["dispatch=true", "next_depth=38"]


def test_continuation_depth_missing_fails_closed(tmp_path):
    result, output = _run_active_check(tmp_path, "Distributed Loop")
    assert result.returncode != 0
    assert output == ""
    assert "fail closed" in result.stderr


def test_continuation_stops_when_another_loop_is_queued_or_running(tmp_path):
    result, output = _run_active_check(
        tmp_path,
        "Distributed Loop (continuation_depth=0)",
        active_count=1,
    )
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["dispatch=false"]
    assert "CONTINUATION_STOP=another_loop_is_active" in result.stdout
    assert "next_depth=" not in output

def test_only_continuous_workflow_owns_automatic_dispatch():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    continuous = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")
    postrun = (root / "distributed-loop-postrun.yml").read_text(encoding="utf-8")

    assert "gh workflow run distributed-autonomous-loop.yml" in continuous
    assert "continuation_depth=" in continuous
    assert "gh workflow run distributed-autonomous-loop.yml" not in postrun
    assert "Automatically continue the verified distributed loop" not in postrun
