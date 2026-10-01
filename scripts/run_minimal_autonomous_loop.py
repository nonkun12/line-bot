"""Minimal, fail-closed autonomous development loop.

This MVP executes at most one queued task by default. A later task is reached
only when the previous guarded runtime returns success. No merge/deploy is
performed here. A kill-switch file or environment variable stops before the
next task.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / ".github" / "autonomous-loop-tasks.json"
DEFAULT_STOP_FILE = Path("/tmp/line-bot-autonomous-loop.stop")


def load_tasks() -> list[dict[str, str]]:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("task queue must contain a list")
    result = []
    for task in tasks:
        if not isinstance(task, dict) or not task.get("id") or not task.get("instruction"):
            raise ValueError("each task needs id and instruction")
        result.append({"id": str(task["id"]), "instruction": str(task["instruction"])})
    return result


def stopped(stop_file: Path) -> bool:
    return (
        os.environ.get("AUTONOMOUS_LOOP_STOP", "").strip().lower() in {"1", "true", "yes", "on"}
        or stop_file.exists()
    )


def run_task(task: dict[str, str], run_index: int) -> dict[str, object]:
    summary = Path("/tmp") / f"minimal-autonomous-{task['id']}.json"
    env = os.environ.copy()
    env["DEV_INSTRUCTION"] = task["instruction"]
    env["AUTONOMOUS_SUMMARY_PATH"] = str(summary)
    env.setdefault("AUTONOMOUS_RUN_SOURCE", "minimal-mvp-loop")
    # Remove any prior summary so a failed/stalled runtime can never inherit an old PASS.
    try:
        summary.unlink()
    except FileNotFoundError:
        pass

    completed = subprocess.run(
        [sys.executable, "scripts/run_guarded_runtime.py"],
        cwd=ROOT,
        env=env,
        text=True,
    )
    status = "FAIL"
    payload: dict[str, object] = {}
    if summary.exists():
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
            status = str(payload.get("status", status))
        except (OSError, ValueError):
            status = "FAIL"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_index": run_index,
        "task_id": task["id"],
        "status": status,
        "exit_code": completed.returncode,
        "base_sha": payload.get("base_sha"),
        "produced_sha": payload.get("produced_sha"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--stop-file", type=Path, default=DEFAULT_STOP_FILE)
    parser.add_argument("--results", type=Path, default=Path("/tmp/minimal-autonomous-loop.jsonl"))
    args = parser.parse_args()

    if args.max_tasks < 1 or args.max_tasks > 3:
        raise SystemExit("--max-tasks must be between 1 and 3")

    tasks = load_tasks()[: args.max_tasks]
    if not tasks:
        print("MINIMAL_LOOP=BLOCKED queue is empty")
        return 1

    args.results.parent.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, 1):
        if stopped(args.stop_file):
            print(f"MINIMAL_LOOP=STOPPED before task={task['id']}")
            return 0

        print(f"MINIMAL_LOOP=RUN task={task['id']} index={index}/{len(tasks)}", flush=True)
        result = run_task(task, index)
        with args.results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")

        if result["exit_code"] != 0 or result["status"] != "PASS":
            print(f"MINIMAL_LOOP=HALT task={task['id']} status={result['status']}", flush=True)
            return 1

        print(f"MINIMAL_LOOP=PASS task={task['id']}", flush=True)

    print("MINIMAL_LOOP=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
