"""Rebuild the bounded autonomous task queue from reviewed deterministic targets.

This does not invent new task IDs or expand file permissions. The runtime's
explicit deterministic target map is the allowlisted source of candidates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping


def build_queue(
    existing_data: dict,
    targets: Mapping[str, str],
    completed_ids: set[str] | frozenset[str] = frozenset(),
) -> dict:
    existing_tasks = existing_data.get("tasks", [])
    if not isinstance(existing_tasks, list):
        raise ValueError("task queue must contain a list")
    by_id = {}
    for task in existing_tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError("existing queue contains an invalid task")
        if task["id"] in by_id:
            raise ValueError("existing queue contains duplicate task IDs")
        by_id[task["id"]] = task

    tasks = []
    for task_id, target in sorted(targets.items()):
        if task_id in completed_ids:
            continue
        if not isinstance(task_id, str) or not task_id or not isinstance(target, str):
            raise ValueError("deterministic target map is invalid")
        normalized = target.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/") or not (
            normalized.startswith("tests/") or normalized.startswith("uhip/tests/")
        ):
            raise ValueError(f"target outside test allowlist: {target}")
        previous = by_id.get(task_id, {})
        instruction = previous.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            instruction = (
                f"Run the deterministic regression-test plan registered for task ID "
                f"{task_id}. Only modify {normalized}; add one focused test if missing. "
                "If the behavior is already covered, report NO_CHANGE. Use dummy data only. "
                "No external communication, secrets, OS actions, merge, or deploy."
            )
        tasks.append({
            "id": task_id,
            "instruction": instruction,
            "allowed_paths": [normalized],
        })

    if not targets:
        raise ValueError("deterministic task catalog is empty")
    return {
        "version": 1,
        "max_tasks_per_run": 4,
        "tasks": tasks,
        "catalog_source": "core.line_development_runtime._DETERMINISTIC_AUTONOMOUS_TASK_TARGETS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=Path(".github/autonomous-loop-tasks.json"))
    parser.add_argument("--state", type=Path, default=Path("/tmp/autonomous-loop-state.json"))
    args = parser.parse_args()
    queue_path = args.queue
    existing = json.loads(queue_path.read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8"))
    completed = state.get("completed", [])
    if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
        raise ValueError("durable state completed list is invalid")
    # Import the reviewed task catalog only; never discover or execute arbitrary paths.
    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS
    rebuilt = build_queue(existing, _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS, set(completed))
    payload = json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n"
    temporary = queue_path.with_name(queue_path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, queue_path)
    print(f"AUTONOMOUS_QUEUE_REBUILT={len(rebuilt['tasks'])}")
    print(f"AUTONOMOUS_QUEUE_SKIPPED_COMPLETED={len(_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS) - len(rebuilt['tasks'])}")
    print("AUTONOMOUS_QUEUE_SOURCE=reviewed_deterministic_catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
