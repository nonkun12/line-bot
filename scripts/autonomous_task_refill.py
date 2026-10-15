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
FORBIDDEN_PREFIXES = (".github/workflows/", "secrets/", ".env", "config/production")


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return data


def build_queue(queue_path: Path, catalog_path: Path, completed_path: Path, output_path: Path) -> dict:
    queue = read_json(queue_path)
    catalog = read_json(catalog_path)
    state = read_json(completed_path)
    existing = queue.get("tasks")
    candidates = catalog.get("tasks")
    completed = state.get("completed", [])
    cap = catalog.get("max_additions_per_run")
    if not isinstance(existing, list) or not isinstance(candidates, list):
        raise ValueError("queue and catalog tasks must be lists")
    if not isinstance(completed, list) or not all(isinstance(x, str) for x in completed):
        raise ValueError("completed state must be a string list")
    if not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= 4:
        raise ValueError("catalog cap must be between 1 and 4")

    seen: set[str] = set()
    normalized = []
    for task in [*existing, *candidates]:
        if not isinstance(task, dict):
            raise ValueError("task must be an object")
        task_id, instruction, paths = task.get("id"), task.get("instruction"), task.get("allowed_paths")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task ID")
        if task_id in seen:
            # Existing queue/catalog overlap is treated as a duplicate, not a second task.
            continue
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 5000:
            raise ValueError("invalid task instruction")
        if not isinstance(paths, list) or not paths or len(paths) > 10:
            raise ValueError("invalid allowed_paths")
        clean_paths = []
        for path in paths:
            if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
                raise ValueError("invalid allowed path")
            parts = Path(path).parts
            if ".." in parts or any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                raise ValueError("forbidden allowed path")
            clean_paths.append(path)
        seen.add(task_id)
        normalized.append({"id": task_id, "instruction": instruction.strip(), "allowed_paths": clean_paths})

    original_ids = {str(t.get("id")) for t in existing if isinstance(t, dict)}
    completed_ids = set(completed)
    additions = [t for t in normalized if t["id"] not in original_ids and t["id"] not in completed_ids][:cap]
    # Keep all existing tasks; add only the bounded next slice from the reviewed catalog.
    final_ids = {t["id"] for t in normalized if t["id"] in original_ids}
    final_tasks = [t for t in normalized if t["id"] in final_ids]
    final_tasks.extend(additions)
    output = {"version": 1, "max_tasks_per_run": min(4, int(queue.get("max_tasks_per_run", 4))), "tasks": final_tasks}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"existing": len(existing), "added": len(additions), "total": len(final_tasks), "added_ids": [t["id"] for t in additions]}


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
