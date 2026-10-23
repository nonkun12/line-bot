"""Import/export a bounded, sanitized self-improvement history in loop state.

Only allowlisted signal kinds, conservative task identifiers, and fixed generic
details are persisted. Raw exceptions, prompts, model output, and user content
are intentionally discarded before durable storage.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MAX_RECORDS = 200
_ALLOWED_KINDS = {"success", "repair", "failure"}
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SAFE_DETAIL = {
    "success": "development reached integration gate",
    "repair": "development required repair attempts",
    "failure": "development failure observed",
}


def sanitize_records(records: object) -> list[dict[str, str | None]]:
    if not isinstance(records, list):
        raise ValueError("self-improvement history must be a list")
    safe: list[dict[str, str | None]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        task_id = row.get("task_id")
        if not isinstance(kind, str) or kind not in _ALLOWED_KINDS:
            continue
        if task_id is not None and (
            not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id)
        ):
            task_id = None
        safe.append({
            "kind": kind,
            "task_id": task_id,
            "detail": _SAFE_DETAIL[kind],
        })
    return safe[-MAX_RECORDS:]


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-MAX_RECORDS:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def atomic_write_jsonl(path: Path, rows: list[dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def append_loop_results(history_path: Path, results_path: Path) -> int:
    """Map exact loop outcomes to their registered task IDs without persisting raw details."""
    additions: list[dict[str, str | None]] = []
    for row in read_jsonl(results_path):
        task_id = row.get("task_id")
        status = row.get("status")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            continue
        if status in {"PASS", "NO_CHANGE"}:
            kind = "success"
        elif status == "FAIL":
            kind = "failure"
        else:
            # BLOCKED/NOT_RUN/STOPPED are not evidence of a task execution failure.
            continue
        additions.append({"kind": kind, "task_id": task_id, "detail": _SAFE_DETAIL[kind]})
    merged = sanitize_records(read_jsonl(history_path) + additions)
    atomic_write_jsonl(history_path, merged)
    return len(additions)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("import", "export", "append-loop-results"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()

    if args.mode == "append-loop-results":
        if args.results is None:
            raise SystemExit("--results is required for append-loop-results")
        count = append_loop_results(args.history, args.results)
        print(f"SELF_IMPROVEMENT_LOOP_RESULTS_APPENDED={count}")
        return 0
    if args.state is None:
        raise SystemExit("--state is required for import/export")

    state = json.loads(args.state.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise SystemExit("durable state must be an object")

    if args.mode == "import":
        records = sanitize_records(state.get("self_improvement_history", []))
        atomic_write_jsonl(args.history, records)
        print(f"SELF_IMPROVEMENT_HISTORY_IMPORTED={len(records)}")
        return 0

    previous = sanitize_records(state.get("self_improvement_history", []))
    # Import runs before the task, so the current file already contains prior
    # durable records plus this run's additions. Do not duplicate the prefix.
    current = sanitize_records(read_jsonl(args.history))
    merged = current if args.history.exists() else previous
    state["self_improvement_history"] = merged
    temp = args.state.with_name(args.state.name + ".tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.state)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"SELF_IMPROVEMENT_HISTORY_EXPORTED={len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
