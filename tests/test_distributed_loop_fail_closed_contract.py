from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unified_loop_candidate_is_inert_and_cannot_run_legacy_queue_logic():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
    for forbidden in (
        "QUEUE_PROGRESS_INVALID",
        "AUTONOMOUS_LOOP_TASK_QUEUE",
        "autonomous-loop-task-catalog.json",
        "autonomous_task_refill",
        "run_minimal_autonomous_loop.py",
        "Resume one explicitly approved held task",
    ):
        assert forbidden not in worker


def test_postrun_flags_blocked_source_report_even_when_conclusion_is_success():
    workflow = (ROOT / ".github/workflows/distributed-loop-postrun.yml").read_text(encoding="utf-8")
    assert 'source_blocked = "- 結果: **BLOCKED**" in original_report' in workflow
    assert 'catalog_blocked = source_blocked and result_reason.startswith((' in workflow
    assert '"catalog_exhausted_held:"' in workflow
    assert '"catalog_exhausted_review_pending:"' in workflow
    assert '"catalog_exhausted_mixed:"' in workflow
    assert "Source workflow final report is BLOCKED" in workflow


def test_candidate_workflow_does_not_publish_or_mutate_runtime_queue():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "Publish verified development branch" not in workflow
    assert "Publish cloud Orca runtime snapshot" not in workflow
    assert "git push" not in workflow
    assert "issues: write" not in workflow
    assert "contents: write" not in workflow


def test_candidate_workflow_has_no_legacy_progress_diagnostics_or_task_report():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    for token in (
        "progress_output_file=/tmp/distributed-loop-queue-progress.out",
        "QUEUE_PROGRESS_BLOCKED:",
        "Queue progress evidence invalid",
        "Task runner step (Actions status)",
        "実タスク結果:",
    ):
        assert token not in workflow


def test_held_catalog_is_not_refilled_or_misreported_as_empty():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    for token in (
        "tee /tmp/autonomous-loop-refill-report.json",
        "catalog_exhausted_held:",
        "catalog_exhausted_review_pending:",
        "review_held_tasks",
    ):
        assert token not in workflow


def test_held_task_resume_is_not_exposed_as_an_executable_worker_action():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    worker = workflow.split("\n  minimal-loop:", 1)[1]
    assert "Resume one explicitly approved held task" not in worker
    assert "confirm_recovery_resume_review" not in worker
    assert "needs.safety-preflight.outputs.execution_enabled == 'true' && false" in worker
