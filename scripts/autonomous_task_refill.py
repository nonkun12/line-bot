"""Build a run-local queue by adding a bounded, reviewed task catalog.

This never mutates the tracked queue or durable completion state. Invalid inputs
fail closed; each run adds at most the catalog's explicit cap.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
ALLOWED_TEST_PATH = re.compile(r"^(tests|uhip/tests)/test_[A-Za-z0-9_]+\.py$")


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return data


def _task_id(task: object) -> str:
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    task_id = task.get("id")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("invalid task ID")
    return task_id


def _validate_task(task: object) -> dict:
    task_id = _task_id(task)
    instruction, paths = task.get("instruction"), task.get("allowed_paths")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 5000:
        raise ValueError("invalid task instruction")
    if not isinstance(paths, list) or not paths or len(paths) > 10:
        raise ValueError("invalid allowed_paths")
    clean_paths = []
    for path in paths:
        if not isinstance(path, str) or not ALLOWED_TEST_PATH.fullmatch(path):
            raise ValueError("forbidden allowed path")
        clean_paths.append(path)
    return {"id": task_id, "instruction": instruction.strip(), "allowed_paths": clean_paths}


def build_queue(queue_path: Path, catalog_path: Path, completed_path: Path, output_path: Path) -> dict:
    queue = read_json(queue_path)
    catalog = read_json(catalog_path)
    state = read_json(completed_path)
    existing = queue.get("tasks")
    candidates = catalog.get("tasks")
    completed = state.get("completed", [])
    cap = catalog.get("max_additions_per_run")
    max_tasks = queue.get("max_tasks_per_run", 4)
    if not isinstance(existing, list) or not isinstance(candidates, list):
        raise ValueError("queue and catalog tasks must be lists")
    if not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("completed state must be a string list")
    if not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= 4:
        raise ValueError("catalog cap must be between 1 and 4")
    if not isinstance(max_tasks, int) or isinstance(max_tasks, bool) or not 1 <= max_tasks <= 4:
        raise ValueError("max_tasks_per_run must be an integer between 1 and 4")

    normalized_existing = []
    original_ids: set[str] = set()
    for raw_task in existing:
        task = _validate_task(raw_task)
        if task["id"] in original_ids:
            raise ValueError("duplicate task ID in existing queue")
        original_ids.add(task["id"])
        normalized_existing.append(task)

    normalized_catalog = []
    catalog_ids: set[str] = set()
    for raw_task in candidates:
        task = _validate_task(raw_task)
        if task["id"] in catalog_ids:
            raise ValueError("duplicate catalog task ID")
        catalog_ids.add(task["id"])
        normalized_catalog.append(task)

    if "recovery_ai" not in state:
        raise ValueError("Recovery AI state is missing")
    recovery = state["recovery_ai"]
    if (not isinstance(recovery, dict) or recovery.get("schema_version") != 1
            or not isinstance(recovery.get("tasks"), dict) or "checkpoint" not in recovery):
        raise ValueError("Recovery AI state is invalid")
    recovery_tasks = recovery["tasks"]
    held_ids = set()
    for task_id, recovery_task in recovery_tasks.items():
        if not isinstance(task_id, str) or not isinstance(recovery_task, dict):
            raise ValueError("invalid Recovery AI task state")
        held = recovery_task.get("held", False)
        if not isinstance(held, bool):
            raise ValueError("invalid Recovery AI held flag")
        if held:
            held_ids.add(task_id)

    completed_ids = set(completed)
    # Completed queue entries must not occupy the bounded window. In particular,
    # a queue containing only completed IDs must not suppress eligible catalog
    # additions while being reported as retained work.
    eligible_existing = [
        task for task in normalized_existing
        if task["id"] not in held_ids and task["id"] not in completed_ids
    ]
    skipped_held_ids = sorted(original_ids.intersection(held_ids))
    skipped_completed_ids = sorted(original_ids.intersection(completed_ids))
    additions = [
        task for task in normalized_catalog
        if task["id"] not in original_ids
        and task["id"] not in completed_ids
        and task["id"] not in held_ids
    ][:cap]
    # Preserve eligible queued tasks, then append only a bounded catalog slice.
    final_tasks = eligible_existing + additions
    output = {"version": 1, "max_tasks_per_run": max_tasks, "tasks": final_tasks}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        # Keep the original input-count field stable for existing consumers.
        "existing": len(existing),
        "retained_existing": len(eligible_existing),
        "skipped_held_ids": skipped_held_ids,
        "skipped_completed_ids": skipped_completed_ids,
        "added": len(additions),
        "total": len(final_tasks),
        "added_ids": [t["id"] for t in additions],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--completed-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_queue(args.queue, args.catalog, args.completed_state, args.output)
    except (ValueError, OSError) as exc:
        print(f"REFILL_BLOCKED: {type(exc).__name__}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
