"""Evidence-only Maintenance AI triage for distributed loop and queue health.

Maintenance AI is an independent observer: it classifies structured run evidence
and queue sentinels, but never edits source, retries tasks, clears holds, publishes,
merges, or deploys.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.loop_failure_codes import is_safe_failure_code

_SAFE_TASK_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_VALID_STATUSES = {"PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN"}
_HELD_COUNT = re.compile(r"^catalog_exhausted_held:[0-9]+$")
_REVIEW_COUNT = re.compile(r"^catalog_exhausted_review_pending:[0-9]+$")
_MIXED_COUNT = re.compile(r"^catalog_exhausted_mixed:held=[0-9]+,review=[0-9]+$")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"result at line {line_number} must be an object")
        rows.append(value)
    return rows


def _read_queue_state(not_run_marker: Path | None, held_marker: Path | None) -> str | None:
    """Translate workflow marker files into a small allowlisted state vocabulary."""
    not_run = not_run_marker is not None and not_run_marker.is_file()
    held = held_marker is not None and held_marker.is_file()
    if not_run and held:
        raise ValueError("conflicting queue state markers")
    if not_run:
        return "queue_empty"
    if not held:
        return None

    try:
        raw = held_marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("queue state marker is unreadable") from exc
    if raw == "all_pending_tasks_held" or _HELD_COUNT.fullmatch(raw):
        return "all_pending_tasks_held"
    if _REVIEW_COUNT.fullmatch(raw):
        return "review_pending"
    if _MIXED_COUNT.fullmatch(raw):
        return "mixed_queue_blocked"
    raise ValueError("queue state marker is not allowlisted")


def _diagnose(row: dict[str, Any]) -> dict[str, Any]:
    task_id = row.get("task_id")
    if not isinstance(task_id, str) or not _SAFE_TASK_ID.fullmatch(task_id):
        task_id = "unidentified-task"
    status = row.get("status")
    status = status if isinstance(status, str) else None
    failure_reason = row.get("failure_reason")
    failure_reason = failure_reason if isinstance(failure_reason, str) else None
    recovery = row.get("recovery_ai")
    recovery = recovery if isinstance(recovery, dict) else {}
    decision = recovery.get("decision")
    decision = decision if isinstance(decision, dict) else {}
    rea = row.get("rea")
    rea = rea if isinstance(rea, dict) else {}
    rea_gate = rea.get("gate")
    rea_gate = rea_gate if isinstance(rea_gate, str) else None
    recovery_action = decision.get("action")
    recovery_action = recovery_action if isinstance(recovery_action, str) else None
    failure_code = row.get("failure_code")
    failure_code = failure_code if is_safe_failure_code(failure_code) else None

    # Independent safety evidence always outranks a nominal PASS.
    if rea_gate in {"BLOCKED", "FAIL"}:
        category = "safety_gate_blocked"
        recommendation = "Review the REA findings; do not retry or bypass the gate."
        requires_human = True
    elif failure_code in {"invalid_change_count", "invalid_change_count_repair_failed"}:
        category = "invalid_plan_change_count"
        recommendation = "The planner did not produce a valid bounded change list. Keep the hold; revise the task to one file and one explicit test addition, then require human review before any resume."
        requires_human = True
    elif recovery_action == "HOLD" or decision.get("requires_human") is True:
        if failure_code == "existing_test_modified_repair_failed":
            category = "test_plan_repair_failed"
            recommendation = "The proposed test edit could not preserve existing tests. Keep the hold; revise the task to append one new test only, then require human review before any resume."
        else:
            category = "recovery_hold"
            recommendation = "Inspect the exact failed step and prepare a reviewed repair proposal; keep the hold."
        requires_human = True
    elif failure_reason == "queue_empty" or status == "NOT_RUN":
        category = "queue_exhausted"
        recommendation = "No task was executed because the executable queue is empty; replenish reviewed tasks before another run."
        requires_human = True
    elif failure_reason == "all_pending_tasks_held":
        category = "all_tasks_held"
        recommendation = "Pending tasks are held; review the hold reasons and explicitly approve any resume."
        requires_human = True
    elif failure_reason == "review_pending":
        category = "review_pending"
        recommendation = "Tasks are waiting for human review; review existing candidates before generating more."
        requires_human = True
    elif failure_reason == "mixed_queue_blocked":
        category = "mixed_queue_blocked"
        recommendation = "The queue contains held and review-pending tasks; resolve the existing review backlog before adding candidates."
        requires_human = True
    elif status in {"PASS", "NO_CHANGE"}:
        category = "completed"
        recommendation = "No maintenance action required."
        requires_human = False
    elif failure_reason == "task_runtime_failed":
        category = "task_runtime_failure"
        recommendation = "Inspect the workflow job log and task summary; classify the concrete error before proposing a patch."
        requires_human = True
    elif status in {"FAIL", "BLOCKED"}:
        category = "unclassified_failure"
        recommendation = "Collect complete run evidence and classify the failure before any retry."
        requires_human = True
    else:
        category = "insufficient_evidence"
        recommendation = "Do not infer success or failure; obtain a complete task result."
        requires_human = True

    allowed_reasons = {
        "task_runtime_failed", "queue_empty", "all_pending_tasks_held",
        "review_pending", "mixed_queue_blocked", "safety_gate_blocked",
        "recovery_ai_requires_hold",
    }
    return {
        "task_id": task_id,
        "status": status if status in _VALID_STATUSES else "UNKNOWN",
        "category": category,
        "failure_reason": failure_reason if failure_reason in allowed_reasons else None,
        "failure_code": failure_code,
        "recovery_action": recovery_action if recovery_action in {
            "CONTINUE", "REPAIR_ONCE", "HOLD", "STOP", "REVIEW",
        } else None,
        "requires_human": requires_human,
        "recommendation": recommendation,
        "permissions": {
            "modify_files": False, "retry_task": False, "clear_hold": False,
            "publish_branch": False, "merge": False, "deploy": False,
        },
    }


def build_report(rows: list[dict[str, Any]], queue_state: str | None = None) -> dict[str, Any]:
    if queue_state is not None:
        queue_rows = {
            "queue_empty": ("NOT_RUN", "queue_empty"),
            "all_pending_tasks_held": ("BLOCKED", "all_pending_tasks_held"),
            "review_pending": ("BLOCKED", "review_pending"),
            "mixed_queue_blocked": ("BLOCKED", "mixed_queue_blocked"),
        }
        if queue_state not in queue_rows:
            raise ValueError("queue state is not allowlisted")
        if not rows:
            status, reason = queue_rows[queue_state]
            rows = [{"task_id": "distributed-loop-queue", "status": status, "failure_reason": reason}]

    if not rows:
        return {
            "schema_version": 1, "agent": "MaintenanceAI",
            "status": "NO_TASK_EVIDENCE", "diagnoses": [],
            "policy": "READ_ONLY_REVIEW_REQUIRED",
            "scope": "DISTRIBUTED_LOOP_AND_QUEUE",
        }
    diagnoses = [_diagnose(row) for row in rows]
    blocked = any(item["requires_human"] for item in diagnoses)
    return {
        "schema_version": 1, "agent": "MaintenanceAI",
        "status": "REVIEW_REQUIRED" if blocked else "NO_ACTION",
        "diagnoses": diagnoses,
        "policy": "READ_ONLY_REVIEW_REQUIRED",
        "scope": "DISTRIBUTED_LOOP_AND_QUEUE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--not-run-marker", type=Path)
    parser.add_argument("--held-marker", type=Path)
    args = parser.parse_args()
    try:
        rows = _load_rows(args.results)
        queue_state = _read_queue_state(args.not_run_marker, args.held_marker)
        report = build_report(rows, queue_state=queue_state)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"MAINTENANCE_AI_STATUS={report['status']}")
    print(f"MAINTENANCE_AI_DIAGNOSES={len(report['diagnoses'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
