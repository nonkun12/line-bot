"""Read-only audit of runtime queue and durable loop/Recovery AI state.

The diagnostic never changes state or unholds tasks. It compares the exact
runtime Recovery AI file with the durable copy and fails closed on missing or
inconsistent evidence. Only task IDs and safe categorical metadata are emitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"invalid_{label}_evidence") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid_{label}_evidence")
    return value


def audit_queue_state(
    queue_path: Path, state_path: Path, recovery_path: Path
) -> dict[str, Any]:
    queue = _load(queue_path, "queue")
    state = _load(state_path, "state")
    recovery = _load(recovery_path, "recovery")

    tasks = queue.get("tasks")
    completed = state.get("completed")
    if not isinstance(tasks, list):
        raise ValueError("invalid_queue_tasks")
    if state.get("version") != 1:
        raise ValueError("invalid_state_schema")
    if not isinstance(completed, list) or not all(
        isinstance(item, str) and item.strip() for item in completed
    ):
        raise ValueError("invalid_completed_state")
    if "recovery_ai" not in state:
        raise ValueError("recovery_state_missing")
    if not isinstance(state["recovery_ai"], dict):
        raise ValueError("invalid_durable_recovery_state")
    if (
        recovery.get("schema_version") != 1
        or not isinstance(recovery.get("tasks"), dict)
        or "checkpoint" not in recovery
    ):
        raise ValueError("invalid_recovery_state")
    if state["recovery_ai"] != recovery:
        raise ValueError("recovery_state_mismatch")

    queue_ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("invalid_queue_task")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("invalid_queue_task_id")
        if task_id in queue_ids:
            raise ValueError("duplicate_queue_task_id")
        queue_ids.append(task_id)

    completed_set = set(completed)
    queue_set = set(queue_ids)
    completed_in_queue = queue_set & completed_set
    pending = queue_set - completed_set
    completed_duplicates = sorted({
        item for item in completed if completed.count(item) > 1
    })
    recovery_tasks = recovery["tasks"]
    held_pending: list[dict[str, Any]] = []
    held_completed: list[str] = []
    review_required: list[str] = []

    for task_id in sorted(queue_set):
        record = recovery_tasks.get(task_id, {})
        if not isinstance(record, dict):
            raise ValueError("invalid_recovery_task_record")
        if record.get("held") is True:
            if task_id in pending:
                category = record.get("last_category")
                failures = record.get("consecutive_failures")
                held_pending.append({
                    "task_id": task_id,
                    "last_category": category if isinstance(category, str) else "unknown",
                    "consecutive_failures": (
                        failures if isinstance(failures, int) and not isinstance(failures, bool)
                        and failures >= 0 else None
                    ),
                })
            else:
                held_completed.append(task_id)
        if record.get("resume_requires_review") is True and task_id in pending:
            review_required.append(task_id)

    pending_count = len(pending)
    held_count = len(held_pending)
    all_pending_held = pending_count > 0 and held_count == pending_count
    if not queue_ids:
        status = "NOT_RUN"
    elif pending_count == 0:
        status = "COMPLETED"
    elif all_pending_held:
        status = "BLOCKED"
    elif held_count:
        status = "WARN"
    else:
        status = "OK"

    warnings = []
    if held_completed:
        warnings.append("held_completed_tasks")
    if review_required:
        warnings.append("resume_requires_review")
    if completed_duplicates:
        warnings.append("duplicate_completed_ids")
    if completed_set - queue_set:
        warnings.append("stale_completed_ids")
    if not queue_ids:
        warnings.append("empty_queue")
    elif pending_count == 0:
        warnings.append("all_tasks_completed")

    return {
        "status": status,
        "queue_total": len(queue_ids),
        "completed_in_queue": len(completed_in_queue),
        "pending_count": pending_count,
        "held_pending_count": held_count,
        "all_pending_held": all_pending_held,
        "pending_task_ids": sorted(pending),
        "held_pending": held_pending,
        "held_completed_task_ids": sorted(held_completed),
        "resume_requires_review_task_ids": sorted(review_required),
        "stale_completed_count": len(completed_set - queue_set),
        "stale_completed_ids": sorted(completed_set - queue_set),
        "duplicate_completed_ids": completed_duplicates,
        "warnings": warnings,
        "no_held_pending": held_count == 0,
        "writes_attempted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_queue_state(args.queue, args.state, args.recovery)
    except (OSError, ValueError, RecursionError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": str(exc) if isinstance(exc, ValueError) else "invalid_evidence",
            "writes_attempted": 0,
        }, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] == "BLOCKED":
        return 1
    if report["status"] == "NOT_RUN":
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
