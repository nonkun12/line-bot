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


def test_distributed_loop_is_scheduled_every_30_minutes_in_tokyo_and_stays_bounded():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"
    source = path.read_text(encoding="utf-8")
    assert "timezone: 'Asia/Tokyo'" in source
    assert "- cron: '*/30 * * * *'" in source
    assert "      MAX_TASKS: '1'" in source
    assert "github.event_name == 'schedule' ||" in source
    assert "FREE_ONLY_EXECUTION_APPROVED: 'false'" in source
    assert "Enforce free-only provider evidence gate" in source
    assert "free_only_provider_and_budget_evidence_missing" in source
    assert "steps.free_only_gate.outcome == 'success'" in source
    assert "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}" not in source
    refill = source.split("      - name: Prepare bounded runtime task refill", 1)[1].split("      - name:", 1)[0]
    assert "--provider-free-only" in refill
    assert "--provider-free-map core/line_development_runtime.py" in refill
    assert "skipped_catalog_not_provider_free_ids" in source
    assert "catalog_blocked_non_provider_free:" in source
    assert "catalog_blocked_unapproved:" in source
    resume = source.split("      - name: Resume one explicitly approved held task", 1)[1].split("      - name:", 1)[0]
    assert "env.FREE_ONLY_EXECUTION_APPROVED == 'true'" in resume
    issue_create = source.split("      - name: Create bounded review-only task issues from analyzer findings", 1)[1].split("      - name:", 1)[0]
    assert "env.FREE_ONLY_EXECUTION_APPROVED == 'true'" in issue_create


def test_orca_phase1_observer_is_manual_only_and_does_not_duplicate_scheduler():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "orca-phase1-read-only-observation.yml"
    source = path.read_text(encoding="utf-8")
    event_block = source.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch:" in event_block
    assert "schedule:" not in event_block
    assert 'cron: "*/30 * * * *"' not in event_block

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
