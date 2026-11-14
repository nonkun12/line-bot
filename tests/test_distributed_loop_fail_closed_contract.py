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
    assert 'source_blocked = "- 結果: **BLOCKED**" in original_report' in workflow
    assert 'catalog_blocked = source_blocked and result_reason.startswith((' in workflow
    assert '"catalog_exhausted_held:"' in workflow
    assert '"catalog_exhausted_review_pending:"' in workflow
    assert '"catalog_exhausted_mixed:"' in workflow
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
    assert 'echo "- Task runner step (Actions status): ${LOOP_OUTCOME:-not_run}"' in workflow
    assert 'echo "- 実タスク結果: $result"' in workflow



def test_held_catalog_exhaustion_is_blocked_not_misreported_as_queue_empty():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "tee /tmp/autonomous-loop-refill-report.json" in workflow
    assert 'eligible == 0 and isinstance(held, list) and held' in workflow
    assert 'catalog_exhausted_held:' in workflow
    assert 'catalog_exhausted_review_pending:' in workflow
    assert 'blocked_detail="$(cat /tmp/autonomous-loop-held-tasks)"' in workflow
    assert "free_only_no_deterministic_tasks" in workflow
    # Held tasks are not auto-released. Re-entry requires the explicit resume
    # request validator plus both cause-fixed and reviewed confirmations.
    assert "- name: Resume one explicitly approved held task" in workflow
    assert "--queue .github/autonomous-loop-task-catalog.json" in workflow
    assert "--cause-fixed" in workflow
    assert "confirm_resume_review" in workflow


def test_held_task_resume_uses_reviewed_catalog_not_only_tracked_queue():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Resume one explicitly approved held task", 1)[1].split("- name: Restore durable Recovery RAG history", 1)[0]
    assert "--queue .github/autonomous-loop-task-catalog.json" in step
    assert "--cause-fixed" in step

def test_free_only_sheets_skip_artifact_is_accepted_by_postrun_verifier():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert '"SKIPPED_FREE_MODE"' in workflow
    assert 'sheets_result not in {"RECORDED", "ALREADY_RECORDED", "SKIPPED_FREE_MODE"}' in workflow
    source = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'result = "SKIPPED_FREE_MODE"' in source
    assert 'distributed-sheets-log-result.json' in source

