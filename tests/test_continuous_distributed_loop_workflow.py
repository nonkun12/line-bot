"""Workflow wiring tests for the independent Chain Job AI continuation owner."""
import os
from pathlib import Path
import subprocess
import textwrap
from types import SimpleNamespace


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "continuous-distributed-loop.yml"
)


def _active_script():
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Avoid duplicate dispatch while another loop is queued or running"
    start = source.index(marker)
    run = source.index("        run: |\n", start) + len("        run: |\n")
    end = source.index("\n      - name: Dispatch the next bounded loop", run)
    return textwrap.dedent(source[run:end])


def _run_active_check(tmp_path, depth, *, active_count=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{active_count}'\n", encoding="utf-8")
    gh.chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env["GATE_DEPTH"] = str(depth)
    env["REPOSITORY"] = "nonkun12/line-bot"
    env["GITHUB_OUTPUT"] = str(output)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["bash", "-c", _active_script()],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.exists() else ""


def _row(task_id="task-one", *, status="PASS", exit_code=0):
    return {
        "task_id": task_id,
        "status": status,
        "exit_code": exit_code,
        "control_tower": {
            "recorded": True,
            "orchestration": {"allow_continue": True},
        },
    }


def _run_gate(tmp_path, rows, completed):
    from scripts.chain_job_ai import decide

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        "".join(__import__("json").dumps(row) + chr(10) for row in rows),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        __import__("json").dumps({"completed": completed}), encoding="utf-8"
    )
    report = decide(evidence, "continuation_depth=0", "success")
    output = "continue=" + ("true" if report["continue"] else "false")
    reason = (
        "task_status_not_successful"
        if report["reason"] == "task_status_not_verified_pass"
        else report["reason"]
    )
    return SimpleNamespace(returncode=0, stdout=f"CONTINUATION_STOP={reason}"), output


def test_continuation_gate_stops_if_any_task_fails(tmp_path):
    from scripts.chain_job_ai import decide

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        __import__("json").dumps(_row(status="FAIL", exit_code=1)),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        __import__("json").dumps({"completed": ["task-one"]}), encoding="utf-8"
    )
    result = decide(evidence, "continuation_depth=0", "success")
    assert result["reason"] == "task_status_not_verified_pass"


def test_continuation_gate_stops_when_task_is_not_run(tmp_path):
    from scripts.chain_job_ai import decide

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "minimal-autonomous-loop.jsonl").write_text(
        __import__("json").dumps(_row("queue-empty-task", status="NOT_RUN", exit_code=78)),
        encoding="utf-8",
    )
    (evidence / "autonomous-loop-state.json").write_text(
        __import__("json").dumps({"completed": []}), encoding="utf-8"
    )
    result = decide(evidence, "continuation_depth=0", "success")
    assert result["continue"] is False
    assert result["reason"] == "task_status_not_verified_pass"


def test_chain_job_ai_is_the_workflow_continuation_decision_owner():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/checkout@v4" in source
    assert "python scripts/chain_job_ai.py" in source
    assert "--max-depth 12" in source
    assert '--github-output "$GITHUB_OUTPUT"' in source
    assert "EVIDENCE_DOWNLOAD_OUTCOME:" in source
    assert "KILL_SWITCH:" in source
    assert "Require successful task status plus durable completion evidence" not in source
    assert "python - <<'PY'" not in source


def test_continuation_depth_is_passed_from_chain_job_ai_and_incremented():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "GATE_DEPTH: ${{ steps.gate.outputs.depth }}" in source
    assert 'depth="$GATE_DEPTH"' in source
    assert '-f continuation_depth="${{ steps.active.outputs.next_depth }}"' in source
    assert "continuation_depth:" in (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")


def test_continuation_depth_zero_dispatches_depth_one(tmp_path):
    result, output = _run_active_check(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["dispatch=true", "next_depth=1"]


def test_continuation_depth_eleven_dispatches_depth_twelve(tmp_path):
    result, output = _run_active_check(tmp_path, 11)
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["dispatch=true", "next_depth=12"]


def test_continuation_depth_missing_fails_closed(tmp_path):
    result, output = _run_active_check(tmp_path, "")
    assert result.returncode != 0
    assert output == ""
    assert "fail closed" in result.stderr


def test_continuation_stops_when_another_loop_is_queued_or_running(tmp_path):
    result, output = _run_active_check(tmp_path, 0, active_count=1)
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["dispatch=false"]
    assert "CONTINUATION_STOP=another_loop_is_active" in result.stdout
    assert "next_depth=" not in output


def test_distributed_loop_uses_adaptive_30_or_60_minute_execution_cadence():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"
    source = path.read_text(encoding="utf-8")
    assert "timezone: 'Asia/Tokyo'" in source
    assert "- cron: '0,30 * * * *'" in source
    assert "cadence-gate:" in source
    assert "pending >= 2 or minute == 0" in source
    assert "github.event_name != 'schedule' || needs.cadence-gate.outputs.run_loop == 'true'" in source
    assert "github.event_name == 'schedule' && '1'" in source
    assert "cadence evidence missing or invalid; refusing scheduled execution" in source
    assert "if task_id not in recovery_tasks:" in source
    assert 'held = record.get("held")' in source
    assert 'review = record.get("resume_requires_review")' in source
    assert "Recovery AI task state missing; refusing scheduled execution" in source


def test_only_continuous_workflow_owns_automatic_dispatch():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    continuous = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")
    postrun = (root / "distributed-loop-postrun.yml").read_text(encoding="utf-8")
    distributed = (root / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "gh workflow run distributed-autonomous-loop.yml" in continuous
    assert "gh workflow run distributed-autonomous-loop.yml" not in postrun
    assert "actions/workflows/distributed-autonomous-loop.yml/dispatches" not in distributed
    assert "Dispatch next bounded job when verified work remains" not in distributed


def test_postrun_verification_does_not_send_a_second_line_report():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-loop-postrun.yml"
    source = path.read_text(encoding="utf-8")
    assert "Always report the completed Loop to LINE" not in source
    assert "LINE duplicate notification disabled (source loop is authoritative)" in source


def test_line_notification_failure_does_not_block_verified_continuation():
    source = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    notification = source.split("      - name: Notify LINE of distributed loop final report", 1)[1].split("      - name:", 1)[0]
    assert "continue-on-error: true" in notification


def _run_real_cadence_decision(tmp_path, tasks, completed, recovery, minute):
    import json
    import sys

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    )
    source = workflow.read_text(encoding="utf-8")
    marker = "      - name: Decide hourly or 30-minute execution"
    start = source.index(marker)
    run = source.index("        run: |\\n", start) + len("        run: |\\n")
    end = source.index("\\n      - name:", run)
    script = textwrap.dedent(source[run:end])
    state_path = tmp_path / "cadence-state.json"
    script = script.replace("/tmp/cadence-state.json", str(state_path))
    queue_path = tmp_path / ".github" / "autonomous-loop-tasks.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    state_path.write_text(
        json.dumps({"completed": completed, "recovery_ai": {"tasks": recovery}}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update({"UTC_MINUTE": minute, "GITHUB_OUTPUT": str(output)})
    result = subprocess.run(
        [sys.executable, "-"],
        input=script,
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.exists() else ""


def test_adaptive_cadence_executes_hourly_at_low_load_and_every_30m_at_high_load(tmp_path):
    def task(task_id):
        return {"id": task_id}

    def ready(task_id):
        return {"held": False, "resume_requires_review": False}

    cases = [
        (0, "00", "true", "0"),
        (1, "30", "false", "1"),
        (2, "30", "true", "2"),
        (4, "30", "true", "4"),
    ]
    for count, minute, expected_run, expected_backlog in cases:
        case_dir = tmp_path / f"case-{count}-{minute}"
        case_dir.mkdir()
        tasks = [task(f"task-{i}") for i in range(count)]
        recovery = {f"task-{i}": ready(f"task-{i}") for i in range(count)}
        result, output = _run_real_cadence_decision(
            case_dir, tasks, [], recovery, minute
        )
        assert result.returncode == 0, result.stderr
        assert f"run_loop={expected_run}" in output
        assert f"backlog={expected_backlog}" in output


def test_adaptive_cadence_excludes_completed_held_and_review_tasks(tmp_path):
    tasks = [{"id": "done"}, {"id": "held"}, {"id": "review"}]
    recovery = {
        "held": {"held": True, "resume_requires_review": False},
        "review": {"held": False, "resume_requires_review": True},
    }
    result, output = _run_real_cadence_decision(
        tmp_path, tasks, ["done"], recovery, "30"
    )
    assert result.returncode == 0, result.stderr
    assert "run_loop=false" in output
    assert "backlog=0" in output


def test_adaptive_cadence_fails_closed_on_missing_or_ambiguous_recovery_evidence(tmp_path):
    tasks = [{"id": "pending"}]
    for recovery in ({}, {"pending": {"held": False}}):
        case_dir = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        case_dir.mkdir()
        result, output = _run_real_cadence_decision(
            case_dir, tasks, [], recovery, "30"
        )
        assert result.returncode != 0
        assert output == ""


def test_adaptive_cadence_fails_closed_on_duplicate_task_ids(tmp_path):
    tasks = [{"id": "same"}, {"id": "same"}]
    recovery = {"same": {"held": False, "resume_requires_review": False}}
    result, output = _run_real_cadence_decision(
        tmp_path, tasks, [], recovery, "30"
    )
    assert result.returncode != 0
    assert output == ""
