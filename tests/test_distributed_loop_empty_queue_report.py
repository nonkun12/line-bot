"""Regression checks for queue-exhausted distributed-loop reporting."""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "distributed-autonomous-loop.yml"
)


def test_empty_queue_is_reported_as_not_run_before_completion_logic():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    not_run = workflow.index(
        'if [ "${LOOP_OUTCOME:-}" = "success" ] && [ "$completed" = "0" ]; then'
    )
    completed = workflow.index(
        'elif [ "${LOOP_OUTCOME:-}" = "success" ] && '
        '{ [ "$completed" = "$requested" ] || [ "$queue_completed" = "$queue_total" ]; }; then',
        not_run,
    )
    empty_queue_branch = workflow[not_run:completed]

    assert 'result="NOT_RUN"' in empty_queue_branch
    assert 'result_reason="queue_exhausted_no_tasks"' in empty_queue_branch
    assert 'result_reason="no_task_executed"' in empty_queue_branch
    assert 'result="COMPLETED"' not in empty_queue_branch


def test_completed_requires_at_least_one_verified_task_in_this_run():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    report_logic = workflow[workflow.index('result="STOPPED/FAILED"'):]
    not_run = report_logic.index('result="NOT_RUN"')
    completed = report_logic.index('result="COMPLETED"')
    assert not_run < completed
    assert '[ "$completed" = "0" ]' in report_logic[:completed]
