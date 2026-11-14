from scripts.run_minimal_autonomous_loop import classify_final_outcome


def test_free_only_final_outcome_accepts_skipped_google_sheets_for_completed_task():
    outcome, reason = classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="skipped",
        recovery_outcome="success",
        requested_tasks=1,
        queue_completed=1,
        queue_total=1,
    )
    assert (outcome, reason) == ("COMPLETED", "required_gates_passed")


def test_free_only_empty_queue_accepts_skipped_google_sheets():
    outcome, reason = classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="skipped",
        recovery_outcome="success",
        queue_empty=True,
        all_tasks_held=False,
        requested_tasks=1,
        queue_completed=0,
        queue_total=0,
    )
    assert (outcome, reason) == ("NOT_RUN", "queue_empty")


def test_free_only_final_outcome_still_blocks_google_sheets_error():
    outcome, reason = classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="failure",
        recovery_outcome="success",
        requested_tasks=1,
        queue_completed=1,
        queue_total=1,
    )
    assert outcome == "FAILED"
    assert "sheets" in reason
