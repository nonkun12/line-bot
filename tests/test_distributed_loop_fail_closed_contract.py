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


def test_resumed_recovery_ai_state_is_persisted_before_held_queue_exit():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    step = workflow.split(
        "- name: Persist explicitly resumed Recovery AI state before held-queue exit", 1
    )[1].split("- name: Persist Recovery AI durable state", 1)[0]
    assert "RESUME_TASK_ID" in step
    assert 'if [ -z "$RESUME_TASK_ID" ]; then' in step
    assert '|| [ ! -f /tmp/autonomous-loop-held-tasks ]' not in step
    assert "resume_requires_review" in step
    assert 'record.get("held") is not False' in step
    assert 'record.get("resume_requires_review") is not True' in step
    assert "git push" in step
    assert "durable Recovery AI read-back mismatch" in step



def test_resumed_recovery_persistence_failure_is_wired_into_final_gates():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    step = workflow.split(
        "- name: Persist explicitly resumed Recovery AI state before held-queue exit", 1
    )[1].split("- name: Persist Recovery AI durable state", 1)[0]
    assert "id: persist_resumed_recovery_ai" in step
    failure_override = (
        "RECOVERY_OUTCOME: ${{ steps.persist_resumed_recovery_ai.outcome == 'failure' "
        "&& 'failure' || steps.persist_recovery_ai.outcome }}"
    )
    # Both Sheets and the final report/classifier must receive the fail-closed outcome.
    assert workflow.count(failure_override) == 2
