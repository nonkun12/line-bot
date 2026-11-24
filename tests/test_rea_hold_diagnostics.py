from scripts.rea_hold_diagnostics import assess_hold_diagnostics, classify_hold_record


def test_review_required_is_manual_and_never_repairable():
    result = classify_hold_record({
        "stage": "pre_execution",
        "reason": "review_required",
        "blocked_tasks": [{"status": "HELD", "hold_reason": "review"}],
    })
    assert result["category"] == "HUMAN_REVIEW"
    assert result["next_action"] == "manual_review"
    assert result["automatic_repair_eligible"] is False
    assert result["hold_clear_authorized"] is False
    assert result["task_resume_authorized"] is False


def test_evidence_gate_is_classified_without_bypass():
    result = classify_hold_record({
        "stage": "pre_execution",
        "reason": "guarded_runtime_or_evidence_gate_failed",
        "blocked_tasks": [],
    })
    assert result["category"] == "EVIDENCE_GATE"
    assert result["next_action"] == "inspect_runtime_or_evidence_gate"
    assert result["execution_authorized"] is False


def test_unknown_reason_uses_allowlisted_failure_evidence():
    result = classify_hold_record({
        "stage": "pre_execution",
        "reason": "future_reason_code",
        "blocked_tasks": [{
            "failure_evidence": {"reason_code": "result_missing_or_ambiguous"}
        }],
    })
    assert result["category"] == "RESULT_COLLECTION_FAILURE"
    assert result["next_action"] == "inspect_result_collection"
    assert result["recovery_path_status"] == "REVIEW_REQUIRED"
    assert result["recovery_requires_human_review"] is True
    assert result["failure_reason_codes"] == ["result_missing_or_ambiguous"]


def test_aggregate_is_bounded_and_never_authorizes_remediation():
    summary = assess_hold_diagnostics([
        {"stage": "pre_execution", "reason": "all_pending_tasks_held"},
        {"stage": "pre_execution", "reason": "review_required"},
    ])
    assert summary["assessment_count"] == 2
    assert summary["category_counts"] == {"HUMAN_REVIEW": 1, "QUEUE_HELD": 1}
    assert summary["automatic_remediation_authorized"] is False
    assert summary["hold_clear_authorized"] is False



def test_guarded_runner_sentinel_is_never_a_repair_candidate():
    result = classify_hold_record({
        "stage": "pre_execution",
        "reason": "failed_or_held_task_requires_review",
        "blocked_tasks": [{
            "failure_evidence": {"reason_code": "guarded_runner_sentinel"}
        }],
    })
    assert result["category"] == "SAFETY_GATE"
    assert result["recovery_path_status"] == "NO_REPAIR"
    assert result["automatic_repair_eligible"] is False
    assert result["hold_clear_authorized"] is False
