from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_invalid_queue_progress_fails_source_workflow():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    marker = 'if [ "${QUEUE_PROGRESS_INVALID:-false}" = "true" ]; then'
    assert marker in workflow
    block = workflow.split(marker, 1)[1].split("\n          fi", 1)[0]
    assert "exit 1" in block


def test_postrun_flags_blocked_source_report_even_when_conclusion_is_success():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert 'if "- 結果: **BLOCKED**" in original_report:' in workflow
    assert "Source workflow final report is BLOCKED" in workflow

def test_publish_gate_uses_the_same_runtime_queue_as_task_execution():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'queue_path = Path(os.environ.get("AUTONOMOUS_LOOP_TASK_QUEUE", ".github/autonomous-loop-tasks.json"))' in workflow



def test_queue_progress_failure_reports_only_safe_diagnostic_class():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'progress_output_file=/tmp/distributed-loop-queue-progress.out' in workflow
    assert '>"$progress_output_file" 2>&1' in workflow
    assert "grep -E '^QUEUE_PROGRESS_BLOCKED: [A-Za-z][A-Za-z0-9_]*" in workflow
    assert 'Queue progress evidence invalid (${progress_diagnostic})' in workflow


def test_persisted_completion_state_is_refreshed_into_postrun_evidence():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    start = workflow.index("- name: Persist completed task state")
    end = workflow.index("- name: Persist Recovery AI durable state", start)
    block = workflow[start:end]

    assert "cp /tmp/autonomous-state-worktree/.autonomous-loop-state.json /tmp/autonomous-loop-state.json" in block
    assert "python -m json.tool /tmp/autonomous-loop-state.json >/dev/null" in block
    assert block.index("git -C /tmp/autonomous-state-worktree push") < block.index(
        "cp /tmp/autonomous-state-worktree/.autonomous-loop-state.json /tmp/autonomous-loop-state.json"
    )
