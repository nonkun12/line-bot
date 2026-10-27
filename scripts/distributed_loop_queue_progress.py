"""Compute queue progress against the exact runtime queue used by the loop.

Progress is a count of unique queue task IDs that are completed in durable state
or have PASS/NO_CHANGE evidence in this run. Held tasks are never cleared here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def calculate_progress(queue_path: Path, state_path: Path, results_path: Path) -> dict[str, int]:
    queue_data = _read_json(queue_path, None)
    if not isinstance(queue_data, dict) or not isinstance(queue_data.get("tasks"), list):
        raise ValueError("invalid runtime queue")
    queue_ids: set[str] = set()
    for item in queue_data["tasks"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError("invalid runtime queue task ID")
        if item["id"] in queue_ids:
            raise ValueError("duplicate runtime queue task ID")
        queue_ids.add(item["id"])

    # Durable state is required evidence. Silently substituting an empty state
    # could make a corrupted/missing state file look like valid zero progress.
    if not state_path.is_file():
        raise ValueError("missing completed state")
    state = _read_json(state_path, None)
    if not isinstance(state, dict) or "completed" not in state or not isinstance(state.get("completed"), list):
        raise ValueError("invalid completed state")
    completed = state["completed"]
    if not all(isinstance(task_id, str) for task_id in completed):
        raise ValueError("invalid completed task ID")
    done_ids = set(completed) & queue_ids

    # Results may be absent if the workflow failed before task execution;
    # the final-outcome classifier separately marks that run BLOCKED/FAIL.
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("invalid task result row")
            task_id = row.get("task_id")
            if row.get("status") in {"PASS", "NO_CHANGE"} and isinstance(task_id, str):
                if task_id in queue_ids:
                    done_ids.add(task_id)

    return {"queue_total": len(queue_ids), "queue_completed": len(done_ids)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = calculate_progress(args.queue, args.state, args.results)
    except Exception as exc:
        # Fail closed and always emit a stable, allowlisted diagnostic for the
        # workflow caller. Do not expose exception messages, paths, or data.
        print(f"QUEUE_PROGRESS_BLOCKED: {type(exc).__name__}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
