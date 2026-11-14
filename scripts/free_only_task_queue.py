"""Filter a runtime queue to exact registered deterministic tasks only.

The upstream refill step remains the approval authority. This adapter narrows
its output; it never adds tasks, changes approval, or mutates durable state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def filter_queue(queue_path: Path, output_path: Path, report_path: Path) -> dict[str, Any]:
    if queue_path.resolve() == output_path.resolve():
        raise ValueError("input and output queue paths must differ")
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("runtime queue is missing or invalid JSON") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        raise ValueError("runtime queue schema version is invalid")
    max_tasks = data.get("max_tasks_per_run")
    if type(max_tasks) is not int or not 1 <= max_tasks <= 4:
        raise ValueError("runtime queue task limit is invalid")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("runtime queue tasks must be a list")

    # Import the version-controlled allowlist only after validating the input
    # envelope. The map is the authoritative ID -> exact path registry.
    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS

    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("runtime queue contains a non-object task")
        task_id = task.get("id")
        instruction = task.get("instruction")
        allowed_paths = task.get("allowed_paths")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            raise ValueError("runtime queue contains an invalid or duplicate task ID")
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 5000:
            raise ValueError(f"runtime queue task instruction is invalid: {task_id}")
        if not isinstance(allowed_paths, list) or not all(isinstance(p, str) for p in allowed_paths):
            raise ValueError(f"runtime queue task allowed_paths is invalid: {task_id}")
        seen.add(task_id)
        expected_path = _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(task_id)
        if expected_path is None:
            excluded.append({"id": task_id, "reason": "not_registered_deterministic"})
            continue
        if allowed_paths != [expected_path]:
            excluded.append({"id": task_id, "reason": "registered_path_mismatch"})
            continue
        accepted.append({
            "id": task_id,
            "instruction": instruction.strip(),
            "allowed_paths": [expected_path],
        })

    output = {"version": 1, "max_tasks_per_run": max_tasks, "tasks": accepted}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "status": "PASS" if accepted else "NO_DETERMINISTIC_TASKS",
        "eligible_deterministic_count": len(accepted),
        "eligible_deterministic_ids": [task["id"] for task in accepted],
        "excluded_count": len(excluded),
        "excluded_tasks": excluded,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = filter_queue(args.queue, args.output, args.report)
    except ValueError as exc:
        raise SystemExit(f"free-only queue filter blocked: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
