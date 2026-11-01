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

from debug_agent.analyzer import analyze_error
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

        # The current task ledger contains reason codes, not exception logs.
        # Run the existing analyzer on that bounded evidence and label its limits.
        analysis = analyze_error(reason)
        diagnoses.append({
            "task_id": task_id,
            "status": status,
            "failure_reason": reason,
            "analysis": {
                "type": analysis.get("type", "Unknown Error"),
                "cause": analysis.get("cause", "原因を特定できません。"),
                "solution": analysis.get("solution", "追加の安全な診断情報が必要です。"),
                "risk": analysis.get("risk", "LOW"),
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
