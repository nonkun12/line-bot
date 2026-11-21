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


def test_preflight_fails_closed_for_malformed_recovery_records_and_flags():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'if not isinstance(recovery, dict):' in workflow
    assert 'raise SystemExit("model_preflight_recovery_record_invalid")' in workflow
    assert 'type(recovery[flag]) is not bool' in workflow
    assert 'raise SystemExit("model_preflight_recovery_flag_invalid")' in workflow



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
    assert "reason = held_reason" in workflow
    assert "action = 'review_held_tasks'" in workflow


def test_held_task_resume_uses_reviewed_catalog_not_only_tracked_queue():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Resume one explicitly approved held task", 1)[1].split("- name: Restore durable Recovery RAG history", 1)[0]
    assert "--queue .github/autonomous-loop-task-catalog.json" in step
    assert "--cause-fixed" in step


def test_postrun_does_not_require_sheets_evidence_when_no_task_was_run():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert "expected_no_task = queue_empty or catalog_blocked" in workflow
    assert 'if not expected_no_task and sheets_result not in {"RECORDED", "ALREADY_RECORDED"}:' in workflow


def test_postrun_treats_missing_task_bound_approval_as_expected_no_task_block():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert '"no_explicitly_approved_tasks"' in workflow
    assert '"all_remaining_tasks_held_or_review_pending"' in workflow
    assert "expected_no_task = queue_empty or catalog_blocked or approval_blocked" in workflow
    assert "APPROVAL_BLOCKED (task-bound approval required; no task executed)" in workflow


def test_postrun_does_not_flag_synthetic_not_run_status_for_approval_block():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert 'if not expected_no_task and any(s not in {"PASS", "NO_CHANGE"} for s in statuses):' in workflow
