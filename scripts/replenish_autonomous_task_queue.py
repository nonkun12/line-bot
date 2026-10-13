"""Safely refill an exhausted autonomous task queue from a reviewed catalog.

This tool only proposes bounded test-only tasks. It never executes tasks, edits
source code, merges, or deploys. Exhausted/held tasks are never re-enqueued.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def replenish_queue(
    queue_path: Path,
    state_path: Path,
    catalog_path: Path,
    recovery_path: Path | None = None,
    *,
    max_add: int = 4,
) -> tuple[bool, str]:
    if not 1 <= max_add <= 4:
        raise ValueError("max_add must be between 1 and 4")
    queue = _read_json(queue_path, {})
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("queue tasks must be a list")
    completed = _read_json(state_path, {"completed": []}).get("completed", [])
    if not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("completed state must be a list of task IDs")
    existing_ids = {
        str(task.get("id")) for task in tasks
        if isinstance(task, dict) and task.get("id")
    }
    completed_ids = set(completed)
    held_ids: set[str] = set()
    if recovery_path is not None:
        recovery = _read_json(recovery_path, {"tasks": {}})
        records = recovery.get("tasks", {})
        if not isinstance(records, dict):
            raise ValueError("Recovery AI tasks state must be an object")
        held_ids = {
            str(task_id) for task_id, record in records.items()
            if isinstance(record, dict) and record.get("held") is True
        }

    pending = [
        str(task.get("id")) for task in tasks
        if isinstance(task, dict) and task.get("id")
        and str(task.get("id")) not in completed_ids
        and str(task.get("id")) not in held_ids
    ]
    if pending:
        return False, "queue_not_empty"
    if any(task_id not in completed_ids for task_id in existing_ids if task_id in held_ids):
        return False, "held_task_requires_review"

    catalog = _read_json(catalog_path, {})
    candidates = catalog.get("tasks")
    if not isinstance(candidates, list):
        raise ValueError("catalog tasks must be a list")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in candidates:
        if not isinstance(task, dict):
            raise ValueError("catalog entry must be an object")
        task_id = task.get("id")
        instruction = task.get("instruction")
        paths = task.get("allowed_paths")
        if not isinstance(task_id, str) or not task_id.strip() or not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("catalog task needs id and instruction")
        if task_id in seen:
            raise ValueError(f"duplicate catalog task id: {task_id}")
        seen.add(task_id)
        if not isinstance(paths, list) or len(paths) != 1 or paths[0] not in {
            "tests/test_minimal_autonomous_loop.py",
            "tests/test_recovery_ai.py",
            "tests/test_management_router.py",
        }:
            raise ValueError(f"catalog task has a non-allowlisted path: {task_id}")
        if task_id in existing_ids or task_id in completed_ids or task_id in held_ids:
            continue
        selected.append({"id": task_id, "instruction": instruction, "allowed_paths": paths})
        if len(selected) >= max_add:
            break

    if not selected:
        return False, "catalog_exhausted_no_safe_tasks"
    queue["version"] = int(queue.get("version", 1))
    queue["max_tasks_per_run"] = min(4, max(1, int(queue.get("max_tasks_per_run", 4))))
    queue["tasks"] = tasks + selected
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, "added:" + ",".join(task["id"] for task in selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--recovery-state", type=Path)
    parser.add_argument("--max-add", type=int, default=4)
    args = parser.parse_args()
    changed, reason = replenish_queue(
        args.queue, args.state, args.catalog, args.recovery_state, max_add=args.max_add
    )
    print(f"QUEUE_REPLENISHMENT={'PROPOSED' if changed else 'NOT_NEEDED'} reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
