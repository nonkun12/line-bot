"""Read-only audit of autonomous-loop queue and durable task state.

This diagnostic never changes task state or unholds tasks. It emits task IDs and
safe categorical fields only; raw exception text, prompts, and secrets are excluded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_{label}_evidence") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid_{label}_evidence")
    return value


def audit_queue_state(queue_path: Path, state_path: Path) -> dict[str, Any]:
    queue = _load(queue_path, "queue")
    state = _load(state_path, "state")
    tasks = queue.get("tasks")
    completed = state.get("completed")
    if not isinstance(tasks, list):
        raise ValueError("invalid_queue_tasks")
    if not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("invalid_completed_state")

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

    queue_set = set(queue_ids)
    completed_set = set(completed)
    completed_in_queue = queue_set & completed_set
    pending = queue_set - completed_set
    recovery = state.get("recovery_ai", {})
    if not isinstance(recovery, dict):
        raise ValueError("invalid_recovery_state")
    recovery_tasks = recovery.get("tasks", {})
    if not isinstance(recovery_tasks, dict):
        raise ValueError("invalid_recovery_tasks")

    held_pending = []
    for task_id in sorted(pending):
        record = recovery_tasks.get(task_id, {})
        if not isinstance(record, dict):
            raise ValueError("invalid_recovery_task_record")
        if record.get("held") is True:
            category = record.get("last_category")
            failures = record.get("consecutive_failures")
            held_pending.append({
                "task_id": task_id,
                "last_category": category if isinstance(category, str) else "unknown",
                "consecutive_failures": failures if isinstance(failures, int) and failures >= 0 else None,
            })

    return {
        "status": "OK" if not held_pending else "BLOCKED",
        "queue_total": len(queue_ids),
        "completed_in_queue": len(completed_in_queue),
        "pending_count": len(pending),
        "held_pending_count": len(held_pending),
        "pending_task_ids": sorted(pending),
        "held_pending": held_pending,
        "stale_completed_count": len(completed_set - queue_set),
        "stale_completed_ids": sorted(completed_set - queue_set),
        "queue_state_consistent": not bool(held_pending),
        "state_mutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_queue_state(args.queue, args.state)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "state_mutated": False}, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
