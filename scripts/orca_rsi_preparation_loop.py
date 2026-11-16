"""Read-only RSI preparation loop: discover, rank, and gate work without dispatching it.

The loop intentionally does not mutate the durable queue, state branch, catalog,
source files, or GitHub Actions. It produces a reviewable candidate report only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError(f"{label}_unreadable_or_ambiguous") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label}_invalid_root")
    return value


def _task_digest(task: dict[str, Any]) -> str:
    # Bind the complete catalog record, including execution approval and any
    # future policy metadata, so a changed authorization cannot reuse a digest.
    canonical = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_report(catalog: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    tasks = catalog.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("catalog_tasks_invalid")
    if type(catalog.get("version")) is not int or catalog["version"] != 1:
        raise ValueError("catalog_version_invalid")
    if type(catalog.get("max_additions_per_run")) is not int or not 1 <= catalog["max_additions_per_run"] <= 4:
        raise ValueError("catalog_run_cap_invalid")

    if type(state.get("schema_version")) is not int or state["schema_version"] != 1:
        blockers.append("orca_state_schema_invalid")
    if type(state.get("revision")) is not int or state["revision"] < 0:
        blockers.append("orca_state_revision_invalid")
    if state.get("global_hold") is not False:
        blockers.append("global_hold_active")
    if state.get("emergency_stop") is not False:
        blockers.append("emergency_stop_active")
    if state.get("active_lease") is not None:
        blockers.append("worker_lease_already_active")

    queue = state.get("tasks")
    if not isinstance(queue, list):
        blockers.append("orca_queue_invalid")
        queue = []
    queued_ids = set()
    seen_queue_ids = set()
    for item in queue:
        if (not isinstance(item, dict)
                or not isinstance(item.get("task_id"), str)
                or not item["task_id"].strip()
                or not isinstance(item.get("status"), str)
                or not item["status"].strip()):
            blockers.append("orca_queue_entry_invalid")
            continue
        if item["task_id"] in seen_queue_ids:
            blockers.append("orca_queue_duplicate_task_id")
        seen_queue_ids.add(item["task_id"])
        if item.get("status") == "queued":
            queued_ids.add(item["task_id"])
    if len(queued_ids) > 1:
        blockers.append("multiple_queued_tasks_present")

    normalized = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("catalog_task_invalid")
        task_id = task.get("id")
        instruction = task.get("instruction")
        paths = task.get("allowed_paths")
        if (not isinstance(task_id, str) or not task_id
                or task_id in seen or not isinstance(instruction, str)
                or not instruction.strip() or not isinstance(paths, list)
                or not paths or any(not isinstance(path, str) or not path for path in paths)):
            raise ValueError("catalog_task_invalid")
        seen.add(task_id)
        normalized.append(task)

    # Legacy catalog flag is candidate eligibility only, never human execution approval.
    catalog_candidates = [task for task in normalized if task.get("execution_approved") is True]
    candidates = []
    for task in catalog_candidates:
        task_id = task["id"]
        if task_id in queued_ids:
            continue
        candidates.append({
            "task_id": task_id,
            "task_digest": _task_digest(task),
            "allowed_paths": task["allowed_paths"],
            "instruction_length": len(task["instruction"]),
            "catalog_candidate_flag": True,
            "execution_approved": False,
            "human_execution_approval_required": True,
            "dispatch_authorized": False,
        })

    if not candidates:
        blockers.append("no_approved_unqueued_catalog_task")
    ready = not blockers and len(candidates) > 0
    return {
        "schema_version": 1,
        "status": "READY_FOR_HUMAN_REVIEW" if ready else "BLOCKED",
        "catalog_task_count": len(normalized),
        "catalog_candidate_flag_count": len(catalog_candidates),
        "candidate_count": len(candidates),
        "candidates": candidates[:catalog["max_additions_per_run"]],
        "blockers": sorted(set(blockers)),
        "decision": "prepare_for_independent_rsi_review" if ready else "wait_without_dispatch",
        "queue_written": False,
        "state_written": False,
        "source_modified": False,
        "worker_started": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "deploy_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(_read_object(args.catalog, "catalog"),
                              _read_object(args.state, "orca_state"))
    except ValueError as exc:
        report = {
            "schema_version": 1, "status": "BLOCKED",
            "blockers": [str(exc)], "candidates": [],
            "queue_written": False, "state_written": False,
            "source_modified": False, "worker_started": False,
            "execution_authorized": False, "merge_authorized": False,
            "deploy_authorized": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
