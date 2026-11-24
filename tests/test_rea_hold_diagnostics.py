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



def test_replay_run_1092_all_pending_tasks_held_evidence():
    # Reconstructed only from the retained Run #1092 state and final report.
    # The original run predates the diagnostic producer, so no JSONL record exists.
    record = {
        "stage": "pre_execution",
        "decision": "HOLD",
        "reason": "all_pending_tasks_held",
        "task_id": None,
        "task_ids": [],
        "task_counts": {"HELD": 1},
        "blocked_tasks": [{
            "task_id": "review-coverage-gap-4f1b715515",
            "status": "HELD",
            "hold_reason": "guarded_runtime_or_evidence_gate_failed",
        }],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    result = classify_hold_record(record)
    assert result["category"] == "QUEUE_HELD"
    assert result["next_action"] == "inspect_held_task_evidence"
    assert result["blocked_task_count"] == 1
    assert result["diagnostic_stage_valid"] is True
    assert result["automatic_repair_eligible"] is False
    assert result["execution_authorized"] is False
    assert result["patch_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["task_resume_authorized"] is False
    assert result["merge_deploy_authorized"] is False



def test_goal_runtime_producer_jsonl_flows_into_rea_consumer(tmp_path):
    # Exercise the real producer and consumer together without running the Loop.
    import json

    from scripts.goal_runtime_bridge import _append_hold_diagnostic

    evidence_path = tmp_path / "goal-autopilot-hold-evaluations.jsonl"
    goal = {
        "tasks": [{
            "task_id": "review-coverage-gap-4f1b715515",
            "status": "HELD",
            "hold_reason": "guarded_runtime_or_evidence_gate_failed",
        }]
    }
    decision = {
        "decision": "HOLD",
        "reason": "all_pending_tasks_held",
        "task_ids": [],
    }

    _append_hold_diagnostic(evidence_path, decision, goal)

    lines = evidence_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    produced_record = json.loads(lines[0])
    assert produced_record["stage"] == "pre_execution"
    assert produced_record["decision"] == "HOLD"
    assert produced_record["task_counts"] == {"HELD": 1}
    assert produced_record["blocked_tasks"][0]["task_id"] == "review-coverage-gap-4f1b715515"

    assessment = assess_hold_diagnostics([produced_record])
    assert assessment["assessment_count"] == 1
    assert assessment["category_counts"] == {"QUEUE_HELD": 1}
    classified = assessment["assessments"][0]
    assert classified["next_action"] == "inspect_held_task_evidence"
    assert classified["blocked_task_count"] == 1
    assert classified["diagnostic_stage_valid"] is True
    assert classified["automatic_repair_eligible"] is False
    assert assessment["automatic_remediation_authorized"] is False
    assert assessment["hold_clear_authorized"] is False
    assert assessment["task_resume_authorized"] is False
    assert produced_record["execution_authorized"] is False
    assert produced_record["patch_authorized"] is False
    assert produced_record["hold_clear_authorized"] is False
    assert produced_record["merge_deploy_authorized"] is False
