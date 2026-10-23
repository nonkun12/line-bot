"""Import/export a bounded, sanitized self-improvement history in loop state.

Only allowlisted signal kinds, conservative task identifiers, and fixed generic
details are persisted. Cycle memory is preserved using categorical fields only;
raw exceptions, paths, prompts, model output, and user content are discarded.
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
    "success": "task passed or verified no-change",
    "repair": "development required repair attempts",
    "failure": "development failure observed",
}
_MEMORY_OUTCOMES = {"PASS", "FAIL", "BLOCKED"}
_MEMORY_CAUSE = {
    "PASS": "development gate passed",
    "FAIL": "development cycle failed",
    "BLOCKED": "development cycle blocked",
}
_MEMORY_IMPROVEMENTS = {
    "PASS": ["retain verified outcome for next cycle"],
    "FAIL": ["review recurring development failure"],
    "BLOCKED": ["resolve safety or evidence block before retry"],
}
_MEMORY_NEXT_ACTION = {
    "PASS": "continue bounded development loop after review",
    "FAIL": "review failure evidence before another attempt",
    "BLOCKED": "require evidence and safety review before resume",
}


def sanitize_records(records: object) -> list[dict[str, object]]:
    """Keep safe task feedback and privacy-filtered cycle memory records."""
    if not isinstance(records, list):
        raise ValueError("self-improvement history must be a list")
    safe: list[dict[str, object]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("record_type") == "cycle_memory":
            outcome = row.get("outcome")
            if not isinstance(outcome, str) or outcome not in _MEMORY_OUTCOMES:
                continue
            # Do not persist free text from model output, exceptions, or paths.
            # Generic bounded fields retain useful outcome context across runs.
            cycle_id = row.get("cycle_id")
            if "cycle_id" in row and (
                not isinstance(cycle_id, str)
                or not re.fullmatch(r"[0-9]{1,20}", cycle_id)
            ):
                continue
            safe_memory = {
                "record_type": "cycle_memory",
                "outcome": outcome,
                "cause": _MEMORY_CAUSE[outcome],
                "improvements": _MEMORY_IMPROVEMENTS[outcome],
                "next_action": _MEMORY_NEXT_ACTION[outcome],
                "target_path": "",
                "recurring_patterns": [],
            }
            if cycle_id is not None:
                safe_memory["cycle_id"] = cycle_id
            safe.append(safe_memory)
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



def validate_durable_history(records: object) -> list[dict[str, object]]:
    """Strictly validate the persisted schema shared with the workflow.

    Unlike sanitize_records(), this rejects unexpected/malformed rows instead
    of silently dropping them; workflow persistence must fail closed.
    """
    if not isinstance(records, list):
        raise ValueError("self-improvement history must be a list")
    if len(records) > MAX_RECORDS:
        raise ValueError("self-improvement history exceeds the record limit")

    validated: list[dict[str, object]] = []
    signal_fields = {"kind", "task_id", "detail"}
    memory_fields = {
        "record_type", "outcome", "cause", "improvements",
        "next_action", "target_path", "recurring_patterns",
    }
    memory_fields_with_cycle_id = memory_fields | {"cycle_id"}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("self-improvement history row must be an object")
        if row.get("record_type") == "cycle_memory":
            outcome = row.get("outcome")
            if set(row) not in (memory_fields, memory_fields_with_cycle_id) or not isinstance(outcome, str) or outcome not in _MEMORY_OUTCOMES:
                raise ValueError("cycle memory schema is invalid")
            expected = {
                "record_type": "cycle_memory",
                "outcome": outcome,
                "cause": _MEMORY_CAUSE[outcome],
                "improvements": _MEMORY_IMPROVEMENTS[outcome],
                "next_action": _MEMORY_NEXT_ACTION[outcome],
                "target_path": "",
                "recurring_patterns": [],
            }
            if "cycle_id" in row:
                cycle_id = row.get("cycle_id")
                if not isinstance(cycle_id, str) or not re.fullmatch(r"[0-9]{1,20}", cycle_id):
                    raise ValueError("cycle memory ID is invalid")
                expected["cycle_id"] = cycle_id
            if row != expected:
                raise ValueError("cycle memory fields are invalid")
            validated.append(expected)
            continue

        if set(row) != signal_fields:
            raise ValueError("self-improvement signal schema is invalid")
        kind, task_id, detail = row.get("kind"), row.get("task_id"), row.get("detail")
        if not isinstance(kind, str) or kind not in _ALLOWED_KINDS:
            raise ValueError("self-improvement signal kind is invalid")
        if task_id is not None and (
            not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id)
        ):
            raise ValueError("self-improvement task ID is invalid")
        if detail != _SAFE_DETAIL[kind]:
            raise ValueError("self-improvement signal detail is invalid")
        validated.append({"kind": kind, "task_id": task_id, "detail": detail})
    return validated


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


def atomic_write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
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


def append_loop_results(
    history_path: Path,
    results_path: Path,
    catalog_path: Path,
    *,
    publish_outcome: str,
    state_outcome: str,
) -> int:
    """Persist only registered task outcomes supported by the workflow gates."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("task catalog must contain a tasks list")
    registered_ids = {
        task.get("id") for task in tasks
        if isinstance(task, dict) and isinstance(task.get("id"), str)
        and _TASK_ID.fullmatch(task["id"])
    }
    gates_passed = publish_outcome == "success" and state_outcome == "success"
    additions: list[dict[str, object]] = []
    for row in read_jsonl(results_path):
        task_id = row.get("task_id")
        status = row.get("status")
        reason = row.get("failure_reason")
        if not isinstance(task_id, str) or task_id not in registered_ids:
            continue
        if status in {"PASS", "NO_CHANGE"}:
            if not gates_passed:
                continue
            kind = "success"
        elif status in {"FAIL", "TIMEOUT"}:
            if isinstance(reason, str) and reason.startswith((
                "summary_", "produced_head_", "blocked_summary_",
                "control_tower_rea:", "run_identity_", "rea_evidence_",
            )):
                continue
            kind = "failure"
        else:
            continue
        additions.append({"kind": kind, "task_id": task_id, "detail": _SAFE_DETAIL[kind]})
    merged = sanitize_records(read_jsonl(history_path) + additions)
    atomic_write_jsonl(history_path, merged)
    return len(additions)



def append_cycle_memory(
    history_path: Path,
    results_path: Path,
    catalog_path: Path,
    *,
    publish_outcome: str,
    state_outcome: str,
    cycle_id: str,
) -> int:
    """Create one privacy-filtered memory, idempotent for a single workflow run."""
    if not isinstance(cycle_id, str) or not re.fullmatch(r"[0-9]{1,20}", cycle_id):
        raise ValueError("invalid cycle ID")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("task catalog must contain a tasks list")
    registered_ids = {
        task.get("id") for task in tasks
        if isinstance(task, dict) and isinstance(task.get("id"), str)
        and _TASK_ID.fullmatch(task["id"])
    }
    gates_passed = publish_outcome == "success" and state_outcome == "success"
    outcome = None
    for row in read_jsonl(results_path):
        task_id, status, reason = row.get("task_id"), row.get("status"), row.get("failure_reason")
        if not isinstance(task_id, str) or task_id not in registered_ids:
            continue
        if status in {"PASS", "NO_CHANGE"}:
            if gates_passed:
                outcome = "PASS"
        elif status in {"FAIL", "TIMEOUT"}:
            if not (isinstance(reason, str) and reason.startswith((
                "summary_", "produced_head_", "blocked_summary_",
                "control_tower_rea:", "run_identity_", "rea_evidence_",
            ))):
                outcome = "FAIL"
        elif status == "BLOCKED":
            outcome = "BLOCKED"
    if outcome is None:
        return 0
    current = sanitize_records(read_jsonl(history_path))
    # Retries for the same workflow run are idempotent; separate runs with the
    # same outcome are distinct observations and must both inform the feedback loop.
    if any(
        row.get("record_type") == "cycle_memory" and row.get("cycle_id") == cycle_id
        for row in current
    ):
        return 0
    memory = {
        "record_type": "cycle_memory",
        "cycle_id": cycle_id,
        "outcome": outcome,
        "cause": _MEMORY_CAUSE[outcome],
        "improvements": _MEMORY_IMPROVEMENTS[outcome],
        "next_action": _MEMORY_NEXT_ACTION[outcome],
        "target_path": "",
        "recurring_patterns": [],
    }
    atomic_write_jsonl(history_path, sanitize_records(current + [memory]))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("import", "export", "append-loop-results", "append-cycle-memory"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--publish-outcome", default="")
    parser.add_argument("--state-outcome", default="")
    parser.add_argument("--cycle-id", default="")
    args = parser.parse_args()

    if args.mode == "append-cycle-memory":
        if args.results is None or args.catalog is None:
            raise SystemExit("--results and --catalog are required for append-cycle-memory")
        count = append_cycle_memory(
            args.history, args.results, args.catalog,
            publish_outcome=args.publish_outcome,
            state_outcome=args.state_outcome,
            cycle_id=args.cycle_id,
        )
        print(f"SELF_IMPROVEMENT_CYCLE_MEMORY_APPENDED={count}")
        return 0
    if args.mode == "append-loop-results":
        if args.results is None or args.catalog is None:
            raise SystemExit("--results and --catalog are required for append-loop-results")
        count = append_loop_results(
            args.history, args.results, args.catalog,
            publish_outcome=args.publish_outcome,
            state_outcome=args.state_outcome,
        )
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
