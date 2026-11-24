"""Deterministic, read-only assessment of pre-execution GoalAutopilot HOLD evidence.

This module classifies evidence for human review. It never authorizes execution,
patching, HOLD clearance, task resumption, merging, or deployment.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


_FAILURE_CLASSES = {
    "guarded_runner_sentinel": (
        "SAFETY_GATE", "preserve_hold_and_inspect_gate", "NO_REPAIR"
    ),
    "runner_nonzero_exit": (
        "RUNNER_FAILURE", "inspect_child_runner_failure", "REVIEW_REQUIRED"
    ),
    "success_evidence_rejected": (
        "EVIDENCE_REJECTED", "compare_result_with_independent_evidence", "REVIEW_REQUIRED"
    ),
    "result_missing_or_ambiguous": (
        "RESULT_COLLECTION_FAILURE", "inspect_result_collection", "REVIEW_REQUIRED"
    ),
}


_REASON_CLASSES = {
    "review_required": ("HUMAN_REVIEW", "manual_review"),
    "execution_not_authorized": ("APPROVAL_REQUIRED", "approval_required"),
    "all_pending_tasks_held": ("QUEUE_HELD", "inspect_held_task_evidence"),
    "guarded_runtime_or_evidence_gate_failed": (
        "EVIDENCE_GATE", "inspect_runtime_or_evidence_gate"
    ),
    "failed_or_held_task_requires_review": (
        "TASK_REQUIRES_REVIEW", "inspect_task_failure_evidence"
    ),
    "unclassified_goal_decision": ("UNKNOWN", "manual_diagnosis"),
    "unknown": ("UNKNOWN", "manual_diagnosis"),
}


def classify_hold_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded deterministic classification; never infer permission."""
    reason = record.get("reason")
    if not isinstance(reason, str):
        reason = "unknown"
    category, next_action = _REASON_CLASSES.get(
        reason, ("UNKNOWN", "manual_diagnosis")
    )

    blocked = record.get("blocked_tasks")
    blocked = blocked if isinstance(blocked, list) else []
    evidence_codes: list[str] = []
    for task in blocked[:50]:
        if not isinstance(task, dict):
            continue
        evidence = task.get("failure_evidence")
        if not isinstance(evidence, dict):
            continue
        code = evidence.get("reason_code")
        if isinstance(code, str) and code.replace("_", "").replace("-", "").isalnum():
            evidence_codes.append(code[:80])

    recovery_path_status = "NOT_PROPOSED"
    if evidence_codes:
        # Prefer a recognized, specific failure code over a broad HOLD reason.
        for code in sorted(set(evidence_codes)):
            mapped = _FAILURE_CLASSES.get(code)
            if mapped:
                category, next_action, recovery_path_status = mapped
                break
        else:
            if category == "UNKNOWN":
                category = "FAILURE_EVIDENCE"
                next_action = "inspect_allowlisted_failure_evidence"

    return {
        "category": category,
        "next_action": next_action,
        "recovery_path_status": recovery_path_status,
        "recovery_requires_human_review": recovery_path_status == "REVIEW_REQUIRED",
        "blocked_task_count": min(len(blocked), 100),
        "failure_reason_codes": sorted(set(evidence_codes))[:20],
        "diagnostic_stage_valid": record.get("stage") == "pre_execution",
        "automatic_repair_eligible": False,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "task_resume_authorized": False,
        "merge_deploy_authorized": False,
    }


def assess_hold_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate deterministic assessments while preserving fail-closed policy."""
    assessments = [classify_hold_record(row) for row in records[:100]]
    counts = Counter(item["category"] for item in assessments)
    return {
        "assessment_count": len(assessments),
        "category_counts": dict(sorted(counts.items())),
        "assessments": assessments,
        "automatic_remediation_authorized": False,
        "hold_clear_authorized": False,
        "task_resume_authorized": False,
    }
