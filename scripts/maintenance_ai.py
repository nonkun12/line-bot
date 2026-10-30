"""Bounded, evidence-only Maintenance AI triage for distributed loop outcomes.
This stage diagnoses structured run evidence. It never edits files, retries tasks,
clears Recovery AI holds, publishes branches, merges, or deploys.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Any

_SAFE_TASK_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_VALID_STATUSES = {"PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN"}


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

    # Safety holds outrank a nominal PASS: contradictory evidence fails closed.
    if rea_gate in {"BLOCKED", "FAIL"}:
        category = "safety_gate_blocked"
        recommendation = "Review the REA findings; do not retry or bypass the gate."
        requires_human = True
    elif recovery_action == "HOLD" or decision.get("requires_human") is True:
        category = "recovery_hold"
        recommendation = "Inspect the exact failed step and prepare a reviewed repair proposal; keep the hold."
        requires_human = True
    elif failure_reason == "queue_empty" or status == "NOT_RUN":
        category = "queue_exhausted"
        recommendation = "No task was executed because the queue is empty; replenish the reviewed task catalog before expecting further work."
        requires_human = True
    elif failure_reason == "all_pending_tasks_held":
        category = "all_tasks_held"
        recommendation = "All pending tasks are held; review the hold reasons and explicitly approve any resume."
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

    return {
        "task_id": task_id,
        "status": status if status in _VALID_STATUSES else "UNKNOWN",
        "category": category,
        "failure_reason": failure_reason if failure_reason in {
            "task_runtime_failed", "queue_empty", "all_pending_tasks_held",
            "safety_gate_blocked", "recovery_ai_requires_hold",
        } else None,
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


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "schema_version": 1, "agent": "MaintenanceAI",
            "status": "NO_TASK_EVIDENCE", "diagnoses": [],
            "policy": "READ_ONLY_REVIEW_REQUIRED",
        }
    diagnoses = [_diagnose(row) for row in rows]
    blocked = any(item["requires_human"] for item in diagnoses)
    return {
        "schema_version": 1, "agent": "MaintenanceAI",
        "status": "REVIEW_REQUIRED" if blocked else "NO_ACTION",
        "diagnoses": diagnoses, "policy": "READ_ONLY_REVIEW_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = _load_rows(args.results)
        report = build_report(rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"MAINTENANCE_AI_STATUS={report['status']}")
    print(f"MAINTENANCE_AI_DIAGNOSES={len(report['diagnoses'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
