"""Read-only diagnostics for Recovery AI HOLD and post-resume review state.

This tool reports evidence requirements only. It never changes durable state,
clears HOLD, approves tasks, or resumes execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def analyze_recovery_holds(
    durable_state: object,
    catalog_document: object,
) -> dict[str, Any]:
    """Summarize held tasks and safe next-evidence requirements without mutation."""
    if not isinstance(durable_state, dict):
        raise ValueError("durable state must be an object")
    if durable_state.get("version") != 1 or not isinstance(durable_state.get("completed"), list):
        raise ValueError("durable state schema invalid")
    completed = durable_state["completed"]
    if any(not isinstance(item, str) or not item for item in completed):
        raise ValueError("completed task IDs invalid")

    recovery = durable_state.get("recovery_ai")
    if (
        not isinstance(recovery, dict)
        or recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise ValueError("durable Recovery AI state invalid")

    if not isinstance(catalog_document, dict) or not isinstance(catalog_document.get("tasks"), list):
        raise ValueError("task catalog schema invalid")

    catalog_by_id: dict[str, dict[str, Any]] = {}
    for task in catalog_document["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("catalog task must be an object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("catalog task ID invalid")
        if task_id in catalog_by_id:
            raise ValueError("duplicate catalog task ID")
        approved = task.get("execution_approved", False)
        if not isinstance(approved, bool):
            raise ValueError("catalog execution approval must be boolean")
        catalog_by_id[task_id] = task

    completed_set = set(completed)
    records = recovery["tasks"]
    diagnostics = []
    for task_id, record in sorted(records.items()):
        if not isinstance(task_id, str) or not task_id or not isinstance(record, dict):
            raise ValueError("Recovery AI task record invalid")
        held = record.get("held")
        review_pending = record.get("resume_requires_review", False)
        if not isinstance(held, bool) or not isinstance(review_pending, bool):
            raise ValueError("Recovery AI hold/review flags ambiguous")

        catalog_task = catalog_by_id.get(task_id)
        approved = catalog_task.get("execution_approved") is True if catalog_task else False
        is_completed = task_id in completed_set
        if not held and not review_pending:
            continue

        if catalog_task is None:
            catalog_status = "MISSING_FROM_CATALOG"
        elif approved:
            catalog_status = "APPROVED"
        else:
            catalog_status = "NOT_APPROVED"

        reason = record.get("hold_reason")
        category = record.get("hold_category") or record.get("last_category")
        if not isinstance(reason, str) or not reason:
            reason = "legacy_hold_reason_unavailable" if held else "post_resume_review_pending"
        if not isinstance(category, str) or not category:
            category = "legacy_hold_category_unavailable" if held else "unknown"

        if review_pending:
            required_evidence = ["independent_post_resume_review", "explicit_review_confirmation"]
            next_step = "complete_post_resume_review_without_running_the_task"
        elif reason in {"non_repairable_failure", "repair_budget_exhausted"}:
            required_evidence = [
                "original_failure_artifact",
                "cause_fixed_change_or_no_change_rationale",
                "focused_regression_tests",
                "independent_rea_verification",
                "explicit_cause_fixed_confirmation",
                "post_resume_review",
            ]
            next_step = "review_original_failure_and_collect_fresh_evidence_before_any_resume"
        else:
            required_evidence = [
                "reconstruct_original_hold_provenance",
                "cause_fixed_change_or_no_change_rationale",
                "focused_regression_tests",
                "independent_rea_verification",
                "explicit_cause_fixed_confirmation",
                "post_resume_review",
            ]
            next_step = "reconstruct_hold_provenance_before_any_resume"

        diagnostics.append({
            "task_id": task_id,
            "catalog_status": catalog_status,
            "completed": is_completed,
            "held": held,
            "resume_review_pending": review_pending,
            "hold_reason": reason,
            "hold_category": category,
            "consecutive_failures": record.get("consecutive_failures"),
            "same_fingerprint_attempts": record.get("same_fingerprint_attempts"),
            "updated_at": record.get("updated_at"),
            "last_decision_action": record.get("last_decision_action"),
            "last_decision_reason": record.get("last_decision_reason"),
            "status": "REVIEW_REQUIRED",
            "next_step": next_step,
            "required_evidence": required_evidence,
        })

    eligible_count = 0
    for task_id, catalog_task in catalog_by_id.items():
        if catalog_task.get("execution_approved") is not True or task_id in completed_set:
            continue
        record = records.get(task_id)
        if record is None:
            eligible_count += 1
            continue
        if not isinstance(record, dict):
            raise ValueError("Recovery AI task record invalid")
        held = record.get("held")
        review_pending = record.get("resume_requires_review", False)
        if not isinstance(held, bool) or not isinstance(review_pending, bool):
            raise ValueError("Recovery AI hold/review flags ambiguous")
        if not held and not review_pending:
            eligible_count += 1

    checkpoint = recovery.get("checkpoint")
    if checkpoint is not None and (
        not isinstance(checkpoint, dict) or checkpoint.get("verified") is not True
    ):
        raise ValueError("Recovery AI checkpoint is ambiguous")

    diagnostics.sort(key=lambda item: item["task_id"])
    held_count = sum(item["held"] for item in diagnostics)
    review_count = sum(item["resume_review_pending"] for item in diagnostics)
    approved_held_count = sum(
        item["held"] and item["catalog_status"] == "APPROVED"
        for item in diagnostics
    )
    return {
        "schema_version": 1,
        "status": "REVIEW_REQUIRED" if diagnostics else "CLEAR",
        "mode": "READ_ONLY",
        "held_count": held_count,
        "resume_review_pending_count": review_count,
        "approved_held_count": approved_held_count,
        "eligible_approved_task_count": eligible_count,
        "checkpoint_available": isinstance(checkpoint, dict),
        "execution_authorized": False,
        "hold_clear_authorized": False,
        "task_resume_authorized": False,
        "diagnostics": diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--catalog", required=True)
    args = parser.parse_args()
    try:
        state = _load_object(args.state_file, "durable state")
        catalog = _load_object(args.catalog, "task catalog")
        result = analyze_recovery_holds(state, catalog)
    except ValueError as exc:
        print(json.dumps({
            "schema_version": 1,
            "status": "BLOCKED",
            "mode": "READ_ONLY",
            "reason": str(exc),
            "execution_authorized": False,
            "hold_clear_authorized": False,
            "task_resume_authorized": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
