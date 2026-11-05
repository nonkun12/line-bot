#!/usr/bin/env python3
"""Collect a read-only Orca orchestration snapshot and optionally publish it.

Only documented read commands are invoked. No Task, Dispatch, or Worker state
is changed. Set ORCA_TERMINAL_HANDLE to the coordinator terminal handle.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

MAX_OUTPUT_BYTES = 1_000_000
COMMAND_TIMEOUT_SECONDS = 30


class CollectionError(RuntimeError):
    pass


def run_orca(args: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> dict[str, Any]:
    completed = subprocess.run(
        ["orca", "orchestration", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    raw = completed.stdout
    if len(raw.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise CollectionError(f"Orca output too large for command: {' '.join(args)}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip()[:500]
        raise CollectionError(
            f"Orca returned invalid JSON for {' '.join(args)}"
            + (f": {detail}" if detail else "")
        ) from exc
    if completed.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is False:
        error = payload.get("error") if isinstance(payload, dict) else None
        raise CollectionError(f"Orca command failed ({' '.join(args)}): {error or completed.stderr[:500]}")
    return payload


def result_object(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise CollectionError("Orca JSON response is missing its result object")
    return result


def result_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = result_object(payload).get(key)
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise CollectionError(f"Orca JSON response has no valid {key} array")
    return values


def collect_snapshot(terminal_handle: str) -> dict[str, Any]:
    if not terminal_handle.strip():
        raise CollectionError("ORCA_TERMINAL_HANDLE is required for task-list")
    task_payload = run_orca([
        "task-list", "--json", "--full", "--from", terminal_handle,
    ])
    task_result = result_object(task_payload)
    tasks = result_list(task_payload, "tasks")

    worker_payload = run_orca([
        "worker-list", "--json", "--full", "--include-remote",
    ])
    workers = result_list(worker_payload, "workers")

    dispatches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id:
            continue
        if task_id in seen:
            continue
        seen.add(task_id)
        dispatch_payload = run_orca([
            "dispatch-show", "--task", task_id, "--json", "--full",
            "--from", terminal_handle,
        ])
        dispatch_result = result_object(dispatch_payload)
        dispatch = dispatch_result.get("dispatch")
        if isinstance(dispatch, dict):
            record = dict(dispatch)
        else:
            record = dict(dispatch_result)
        record.setdefault("task_id", task_id)
        dispatches.append(record)

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "run_id": task_result.get("runId"),
        "tasks": tasks,
        "dispatches": dispatches,
        "workers": workers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="pipe the snapshot to orca_status_publisher.py")
    parser.add_argument("--publisher", default=None, help="publisher script path; defaults beside this file")
    args = parser.parse_args(argv)

    if shutil.which("orca") is None:
        parser.error("orca CLI was not found on PATH")
    handle = os.environ.get("ORCA_TERMINAL_HANDLE", "").strip()
    try:
        snapshot = collect_snapshot(handle)
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        if args.publish:
            publisher = args.publisher or os.path.join(os.path.dirname(__file__), "orca_status_publisher.py")
            completed = subprocess.run(
                [sys.executable, publisher],
                input=encoded,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            return completed.returncode
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    except (CollectionError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Orca snapshot not collected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
