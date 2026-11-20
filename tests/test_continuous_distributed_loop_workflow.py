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


def test_continuation_depth_is_only_observability_metadata_not_execution_authority():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "GATE_DEPTH: ${{ steps.gate.outputs.depth }}" in source
    assert 'depth="$GATE_DEPTH"' in source
    assert "gh workflow run distributed-autonomous-observation.yml" in source
    assert "gh workflow run distributed-autonomous-loop.yml" not in source


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


def test_distributed_loop_is_manual_approved_and_observation_is_scheduled():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    execution = (root / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    observation = (root / "distributed-autonomous-observation.yml").read_text(encoding="utf-8")
    trigger_block = execution.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "schedule:" not in trigger_block
    assert "issue_comment:" not in trigger_block
    assert "pull_request_target:" not in trigger_block
    assert "execution_approval:" in trigger_block
    assert "default: 'DENY'" in trigger_block
    assert 'cron: "0,30 * * * *"' in observation


def test_automatic_continuations_can_dispatch_observation_but_never_execution():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    continuous = (root / "continuous-distributed-loop.yml").read_text(encoding="utf-8")
    safe = (root / "distributed-loop-safe-continuation.yml").read_text(encoding="utf-8")
    postrun = (root / "distributed-loop-postrun.yml").read_text(encoding="utf-8")
    distributed = (root / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    for source in (continuous, safe):
        assert "gh workflow run distributed-autonomous-observation.yml" in source
        assert "gh workflow run distributed-autonomous-loop.yml" not in source
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

def test_continuation_is_triggered_by_completed_distributed_loop_workflow():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflow_run:' in source
    assert 'workflows: ["Distributed Autonomous Development Loop"]' in source
    assert 'types: [completed]' in source
    assert "github.event_name == 'workflow_run'" in source
    assert "github.event.workflow_run.name == 'Distributed Autonomous Development Loop'" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "workflow_dispatch:" not in source.split("permissions:", 1)[0]


def test_continuation_checks_both_execution_and_observation_for_duplicates():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/workflows/distributed-autonomous-loop.yml/runs?per_page=20" in source
    assert "actions/workflows/distributed-autonomous-observation.yml/runs?per_page=20" in source
    assert 'active_loop" -gt 0' in source
    assert 'active_observation" -gt 0' in source
    assert "another_loop_or_observation_is_active" in source


def test_continuation_remains_read_only_and_never_dispatches_execution():
    source = WORKFLOW.read_text(encoding="utf-8")
    permissions = source.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "actions: write" not in permissions
    assert "contents: write" not in permissions
    assert "gh workflow run distributed-autonomous-observation.yml" in source
    assert "gh workflow run distributed-autonomous-loop.yml" not in source
