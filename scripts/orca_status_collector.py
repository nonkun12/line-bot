#!/usr/bin/env python3
"""Collect a bounded, read-only Orca status snapshot and optionally publish it."""
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
# Never forward arbitrary --full records. These are display-only operational fields.
TASK_FIELDS = {"id", "task_id", "status", "state", "stage", "created_at", "updated_at", "dispatch_id", "worker_id", "stream_key"}
DISPATCH_FIELDS = {"id", "dispatch_id", "task_id", "status", "state", "stage", "created_at", "updated_at", "worker_id", "stream_key"}
WORKER_FIELDS = {"id", "worker_id", "dispatch_id", "task_id", "status", "state", "stage", "addressable", "exactWorker", "created_at", "updated_at", "stream_key"}
STREAMS = {
    "main_star_night": ("STAR-NIGHT", "main"),
    "side_task_supply": ("タスク枯渇対策", "side"),
    "side_media_ai": ("映像・音楽AI", "side"),
    "side_self_improvement": ("自己改善AI", "side"),
    "side_line_full_control": ("LINE全指示化", "side"),
}

class CollectionError(RuntimeError):
    pass


def _safe_record(record: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    safe = {key: value for key, value in record.items()
            if key in allowed and isinstance(value, (str, int, float, bool)) and len(str(value)) <= 160}
    # Derive the stream association locally from source metadata, but never
    # transmit free-form titles, names, project labels, prompts, or descriptions.
    stream_key = _stream_key(record)
    if stream_key:
        safe["stream_key"] = stream_key
    return safe


def run_orca(args: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> dict[str, Any]:
    completed = subprocess.run(["orca", "orchestration", *args], check=False,
                               capture_output=True, text=True, timeout=timeout)
    raw = completed.stdout
    if len(raw.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise CollectionError("Orca output too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollectionError("Orca returned invalid JSON") from exc
    if completed.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is False:
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else "command_failed"
        raise CollectionError(f"Orca command failed: {code}")
    return payload


def result_object(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise CollectionError("Orca response is missing result object")
    return result


def result_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = result_object(payload).get(key)
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise CollectionError(f"Orca response has no valid {key} array")
    return values


def _stream_key(record: dict[str, Any]) -> str | None:
    explicit = record.get("stream_key")
    if explicit in STREAMS:
        return explicit
    haystack = " ".join(str(record.get(k, "")) for k in ("project", "kind", "title", "name")).casefold()
    aliases = {
        "main_star_night": ("star-night", "star night"),
        "side_task_supply": ("タスク枯渇対策", "task supply"),
        "side_media_ai": ("映像・音楽ai", "映像ai", "音楽ai", "video/music"),
        "side_self_improvement": ("自己改善ai", "self-improvement"),
        "side_line_full_control": ("line全指示化", "line secretary"),
    }
    for key, terms in aliases.items():
        if any(term.casefold() in haystack for term in terms):
            return key
    return None


def build_streams(tasks: list[dict[str, Any]], dispatches: list[dict[str, Any]],
                  workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    streams = []
    for key, (label, kind) in STREAMS.items():
        matched = [t for t in tasks if _stream_key(t) == key]
        task_ids = {str(t.get("id") or t.get("task_id") or "") for t in matched}
        related_dispatches = [d for d in dispatches if _stream_key(d) == key or str(d.get("task_id", "")) in task_ids]
        dispatch_ids = {str(d.get("id") or d.get("dispatch_id") or "") for d in related_dispatches}
        related_workers = [w for w in workers if _stream_key(w) == key or str(w.get("task_id", "")) in task_ids or str(w.get("dispatch_id", "")) in dispatch_ids]
        streams.append({
            "key": key, "label": label, "kind": kind,
            "status": "observed" if matched or related_dispatches or related_workers else "unknown",
            "task_count": len(matched), "dispatch_count": len(related_dispatches),
            "worker_count": len(related_workers),
            "evidence": "matched_runtime_records" if matched or related_dispatches or related_workers else "no_matching_stream_metadata",
        })
    return streams


def collect_snapshot(terminal_handle: str) -> dict[str, Any]:
    if not terminal_handle.strip():
        raise CollectionError("ORCA_TERMINAL_HANDLE is required")
    task_payload = run_orca(["task-list", "--json", "--full", "--from", terminal_handle])
    task_result = result_object(task_payload)
    tasks = [_safe_record(x, TASK_FIELDS) for x in result_list(task_payload, "tasks")]
    worker_payload = run_orca(["worker-list", "--json", "--full", "--include-remote"])
    workers = [_safe_record(x, WORKER_FIELDS) for x in result_list(worker_payload, "workers")]
    dispatches = []
    seen = set()
    for task in tasks:
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        response = run_orca(["dispatch-show", "--task", task_id, "--json", "--full", "--from", terminal_handle])
        result = result_object(response)
        item = result.get("dispatch")
        if not isinstance(item, dict):
            item = result
        safe = _safe_record(item, DISPATCH_FIELDS)
        safe.setdefault("task_id", task_id)
        dispatches.append(safe)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(task_result.get("runId") or "")[:100],
        "tasks": tasks, "dispatches": dispatches, "workers": workers,
        "streams": build_streams(tasks, dispatches, workers),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--publisher", default=None)
    args = parser.parse_args(argv)
    if shutil.which("orca") is None:
        parser.error("orca CLI was not found on PATH")
    try:
        snapshot = collect_snapshot(os.environ.get("ORCA_TERMINAL_HANDLE", "").strip())
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        if args.publish:
            publisher = args.publisher or os.path.join(os.path.dirname(__file__), "orca_status_publisher.py")
            completed = subprocess.run([sys.executable, publisher], input=encoded, text=True,
                                       check=False, timeout=COMMAND_TIMEOUT_SECONDS)
            return completed.returncode
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    except (CollectionError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Orca snapshot not collected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
