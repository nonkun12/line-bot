"""Read-only Debug Agent bridge for distributed-loop structured failures.

Only allowlisted status/reason codes are consumed. Raw task output, exception text,
instructions, secrets, and arbitrary JSON fields are never copied into the report.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from debug_agent.safety import SafetyGuard

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_REASONS = {
    "task_runtime_failed", "task_timeout", "stop_requested_during_task",
    "stop_requested_after_task", "stop_requested_before_task",
    "summary_not_object", "summary_invalid_json", "summary_missing_required_key",
    "summary_sha_invalid", "summary_exit_code_mismatch", "summary_stale",
    "summary_timestamp_future", "summary_timestamp_invalid",
    "summary_identity_mismatch", "summary_base_sha_mismatch",
    "blocked_summary_rea_evidence_invalid", "blocked_summary_failure_reason_invalid",
    "blocked_summary_missing_rea_evidence", "summary_status_invalid",
    "summary_produced_sha_mismatch", "summary_no_change_but_head_moved",
    "control_tower_head_changed", "control_tower_kill_switch_enabled",
    "control_tower_catalog:catalog_unavailable_or_invalid",
    "control_tower_recovery_state:unavailable_or_invalid",
    "queue_empty", "all_pending_tasks_held",
}
_FAILURE_STATUSES = {"FAIL", "BLOCKED", "TIMEOUT", "STOPPED"}



_REASON_DIAGNOSES = {
    "task_runtime_failed": ("Task execution failure", "The task runner reported a failed task.", "Inspect the task's bounded failure metadata and rerun only after review."),
    "task_timeout": ("Task timeout", "The task exceeded its configured execution window.", "Check workload size and bounded timeout settings before retrying."),
    "stop_requested_during_task": ("Stop requested", "A stop request arrived while a task was running.", "Confirm the stop request was intentional; do not auto-resume."),
    "stop_requested_after_task": ("Stop requested", "A stop request was recorded after task completion.", "Review the stop request and final task evidence."),
    "stop_requested_before_task": ("Stop requested", "A stop request prevented task execution.", "Review the stop request before starting another run."),
    "summary_not_object": ("Invalid task evidence", "The task summary was not a JSON object.", "Repair the summary producer and validate the schema."),
    "summary_invalid_json": ("Invalid task evidence", "The task summary could not be parsed as JSON.", "Repair the summary serialization and rerun validation."),
    "summary_missing_required_key": ("Incomplete task evidence", "A required summary field was missing.", "Restore the required evidence fields before publication."),
    "summary_sha_invalid": ("Invalid task evidence", "The reported SHA did not match the expected format.", "Check the SHA generation and validation path."),
    "summary_exit_code_mismatch": ("Inconsistent task evidence", "The reported status and process exit code disagreed.", "Reconcile the task result and process exit code."),
    "summary_stale": ("Stale task evidence", "The summary was older than the permitted evidence window.", "Regenerate evidence from the current run."),
    "summary_timestamp_future": ("Invalid task evidence", "The summary timestamp was in the future.", "Check timestamp generation and clock handling."),
    "summary_timestamp_invalid": ("Invalid task evidence", "The summary timestamp was invalid.", "Correct timestamp serialization and validate again."),
    "summary_identity_mismatch": ("Task identity mismatch", "The summary identity did not match the active task.", "Verify task identity propagation end to end."),
    "summary_base_sha_mismatch": ("Base revision mismatch", "The summary was produced against a different base revision.", "Regenerate evidence against the current base SHA."),
    "blocked_summary_rea_evidence_invalid": ("REA evidence blocked", "REA safety evidence failed validation.", "Review the REA evidence schema; keep publication blocked."),
    "blocked_summary_failure_reason_invalid": ("Failure reason blocked", "The failure reason was not allowlisted.", "Use a documented reason code; do not pass raw exception text."),
    "blocked_summary_missing_rea_evidence": ("REA evidence missing", "Required REA safety evidence was absent.", "Restore the required REA evidence before proceeding."),
    "summary_status_invalid": ("Invalid task status", "The summary contained an unsupported status.", "Use only the documented task status values."),
    "summary_produced_sha_mismatch": ("Produced revision mismatch", "The produced SHA did not match the checked-out result.", "Verify the resulting commit and evidence SHA."),
    "summary_no_change_but_head_moved": ("Unexpected repository change", "The repository HEAD moved although the task claimed no change.", "Inspect the diff and commit history before any publication."),
    "control_tower_head_changed": ("Control Tower guard blocked", "The repository HEAD changed during the guarded run.", "Reconcile the current HEAD and rerun the preflight checks."),
    "control_tower_kill_switch_enabled": ("Control Tower kill switch", "The configured kill switch prevented execution.", "Keep the loop stopped until an authorized operator clears the condition."),
    "control_tower_catalog:catalog_unavailable_or_invalid": ("Task catalog unavailable", "The task catalog was missing or invalid.", "Repair and validate the catalog before restarting the loop."),
    "control_tower_recovery_state:unavailable_or_invalid": ("Recovery state unavailable", "The durable recovery state was missing or invalid.", "Restore a validated recovery state; do not bypass this guard."),
    "queue_empty": ("No pending tasks", "The distributed-loop queue contained no executable tasks.", "Add reviewed tasks to the catalog before starting another run."),
    "all_pending_tasks_held": ("All tasks held", "Every pending task was held by a safety or review gate.", "Review each hold cause; do not clear holds automatically."),
    "unclassified_failure": ("Unclassified failure", "The structured reason code was not recognized.", "Collect additional sanitized evidence and request human review."),
}

def _diagnosis(reason: str) -> tuple[str, str, str, str]:
    kind, cause, solution = _REASON_DIAGNOSES.get(reason, _REASON_DIAGNOSES["unclassified_failure"])
    risk = "HIGH" if reason.startswith("blocked_summary_") or reason == "control_tower_kill_switch_enabled" else "LOW"
    return kind, cause, solution, risk


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"result at line {number} must be an object")
        rows.append(value)
    return rows


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if (SafetyGuard.MODE != "read_only" or SafetyGuard.can_modify_file()
            or SafetyGuard.can_git_commit() or SafetyGuard.can_git_push()
            or SafetyGuard.can_deploy()):
        raise RuntimeError("Debug Agent safety policy is not read-only")

    diagnoses = []
    for row in rows:
        status = row.get("status")
        if status not in _FAILURE_STATUSES:
            continue
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not _SAFE_TASK_ID.fullmatch(task_id):
            task_id = "unidentified-task"
        raw_reason = row.get("failure_reason")
        reason = raw_reason if isinstance(raw_reason, str) and raw_reason in _ALLOWED_REASONS else "unclassified_failure"

        # Use deterministic descriptions for structured codes; do not pass
        # opaque codes to a keyword analyzer that would label them all unknown.
        kind, cause, solution, risk = _diagnosis(reason)
        diagnoses.append({
            "task_id": task_id,
            "status": status,
            "failure_reason": reason,
            "analysis": {
                "type": kind,
                "cause": cause,
                "solution": solution,
                "risk": risk,
                "evidence_scope": "allowlisted_structured_reason_code_only",
                "limitations": "Raw traceback and exception class are not present in the task ledger; this is preliminary triage.",
            },
            "permissions": {
                "modify_files": False, "git_commit": False, "git_push": False,
                "retry_task": False, "clear_hold": False, "merge": False, "deploy": False,
            },
            "requires_human": True,
        })

    return {
        "schema_version": 1,
        "agent": "DebugAgent",
        "mode": SafetyGuard.MODE,
        "status": "REVIEW_REQUIRED" if diagnoses else "NO_FAILURES",
        "diagnoses": diagnoses,
        "policy": "READ_ONLY_NO_REPAIR_NO_RETRY_NO_PUBLISH",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(_load_rows(args.results))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"DEBUG_AGENT_STATUS={report['status']}")
    print(f"DEBUG_AGENT_DIAGNOSES={len(report['diagnoses'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
