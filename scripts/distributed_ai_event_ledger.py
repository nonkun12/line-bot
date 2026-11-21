"""Build a validated, per-run event ledger for distributed AI handoffs.

The ledger is append-only within a run. It records assignment, execution and
verification evidence without granting approval, changing HOLD state, or
launching work. Events are deterministic so repeated exports are idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EVENTS_SCHEMA_VERSION = 1
ALLOWED_EVENT_TYPES = {
    "task.assigned",
    "task.started",
    "task.completed",
    "task.failed",
    "task.blocked",
}
TERMINAL_RESULT_STATUSES = {"PASS", "FAIL", "BLOCKED", "NO_CHANGE", "STOPPED"}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid JSON input: {path.name}") from exc


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL row: {path.name}:{line_number}")
            rows.append(row)
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid JSONL input: {path.name}") from exc
    return rows


def _event(run_id: str, task_id: str, event_type: str, actor: str, details: dict) -> dict:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("unsupported event type")
    payload = {
        "schema_version": EVENTS_SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "event_type": event_type,
        "actor": actor,
        "details": details,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {"event_id": hashlib.sha256(encoded.encode("utf-8")).hexdigest(), **payload}


def build_event_ledger(
    queue_path: Path, results_path: Path, output_path: Path, run_id: str
) -> dict:
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 100:
        raise ValueError("invalid run ID")
    queue = _read_json(queue_path, {"tasks": []})
    if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
        raise ValueError("invalid runtime queue")
    tasks = queue["tasks"]
    results = _read_jsonl(results_path)
    task_by_id: dict[str, dict] = {}
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
            raise ValueError("invalid queued task")
        if task["id"] in task_by_id:
            raise ValueError("duplicate queued task ID")
        task_by_id[task["id"]] = task

    result_by_id: dict[str, dict] = {}
    for result in results:
        task_id = result.get("task_id") or result.get("id")
        if not isinstance(task_id, str) or task_id not in task_by_id:
            # Ignore non-task diagnostics, but never infer a task from free text.
            continue
        if task_id in result_by_id:
            raise ValueError("duplicate result for task")
        result_by_id[task_id] = result

    events: list[dict] = []
    for task_id, task in task_by_id.items():
        events.append(_event(
            run_id, task_id, "task.assigned", "coordinator",
            {"allowed_paths": task.get("allowed_paths", [])},
        ))
        result = result_by_id.get(task_id)
        if result is None:
            continue
        raw_status = result.get("status") or result.get("outcome") or result.get("result")
        status = raw_status.upper() if isinstance(raw_status, str) else ""
        if status not in TERMINAL_RESULT_STATUSES:
            status = "FAIL"
        event_type = {
            "PASS": "task.completed",
            "NO_CHANGE": "task.completed",
            "FAIL": "task.failed",
            "BLOCKED": "task.blocked",
            "STOPPED": "task.blocked",
        }[status]
        if status not in {"BLOCKED", "STOPPED"}:
            events.append(_event(run_id, task_id, "task.started", "runner", {}))
        evidence = {
            "status": status,
            "has_test_evidence": bool(result.get("tests") or result.get("test_result") or result.get("test_summary")),
            "has_artifact_evidence": bool(result.get("artifact") or result.get("artifacts")),
        }
        events.append(_event(run_id, task_id, event_type, "verifier", evidence))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    counts = {event_type: 0 for event_type in sorted(ALLOWED_EVENT_TYPES)}
    for event in events:
        counts[event["event_type"]] += 1
    return {
        "schema_version": EVENTS_SCHEMA_VERSION,
        "run_id": run_id,
        "event_count": len(events),
        "task_count": len(task_by_id),
        "result_count": len(result_by_id),
        "event_counts": counts,
        "ledger_path": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        report = build_event_ledger(args.queue, args.results, args.output, args.run_id)
    except (ValueError, OSError) as exc:
        print("DISTRIBUTED_AI_LEDGER_BLOCKED: " + type(exc).__name__)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
