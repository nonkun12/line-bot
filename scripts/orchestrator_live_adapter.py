#!/usr/bin/env python3
"""Build a read-only Orchestrator snapshot from the repository's real ledgers.

The adapter never refills queues, writes state, dispatches Actions, or authorizes
execution. Missing/stale Global HOLD or budget evidence fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_TASKS = 500
HARD_BUDGET_MINUTES = 2000
MAX_EVIDENCE_AGE_SECONDS = 3600


class SnapshotError(ValueError):
    """A source ledger is malformed or inconsistent."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SnapshotError(f"{label}_unavailable") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{label}_invalid_json") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _id_map(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
        raise SnapshotError(f"{label}_invalid_tasks")
    items = value["tasks"]
    if len(items) > MAX_TASKS:
        raise SnapshotError(f"{label}_too_many_tasks")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise SnapshotError(f"{label}_task_not_object")
        task_id = item.get("id")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 120:
            raise SnapshotError(f"{label}_invalid_task_id")
        if task_id in result:
            raise SnapshotError(f"{label}_duplicate_task_id")
        result[task_id] = item
    return result


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError(f"{label}_timestamp_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{label}_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise SnapshotError(f"{label}_timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _freshness(observed_at: Any, now: datetime, label: str) -> int:
    observed = _parse_time(observed_at, label)
    age = int((now - observed).total_seconds())
    if age < -60:
        raise SnapshotError(f"{label}_timestamp_in_future")
    if age > MAX_EVIDENCE_AGE_SECONDS:
        raise SnapshotError(f"{label}_stale")
    return max(age, 0)


def _validate_state(document: Any) -> tuple[set[str], dict[str, dict[str, Any]]]:
    if not isinstance(document, dict) or type(document.get("version")) is not int or document.get("version") != 1:
        raise SnapshotError("durable_state_invalid")
    completed = document.get("completed")
    recovery = document.get("recovery_ai")
    if not isinstance(completed, list) or any(not isinstance(x, str) or not x for x in completed):
        raise SnapshotError("durable_completed_invalid")
    if not isinstance(recovery, dict) or type(recovery.get("schema_version")) is not int or recovery.get("schema_version") != 1:
        raise SnapshotError("recovery_state_invalid")
    recovery_tasks = recovery.get("tasks")
    if not isinstance(recovery_tasks, dict):
        raise SnapshotError("recovery_tasks_invalid")
    for task_id, entry in recovery_tasks.items():
        if not isinstance(task_id, str) or not isinstance(entry, dict):
            raise SnapshotError("recovery_task_entry_invalid")
        for flag in ("held", "resume_requires_review"):
            if flag in entry and not isinstance(entry[flag], bool):
                raise SnapshotError("recovery_task_flag_invalid")
    if len(completed) != len(set(completed)):
        raise SnapshotError("durable_completed_duplicate")
    return set(completed), recovery_tasks


def _validate_hold(path: Path | None, now: datetime) -> tuple[bool, bool, int | None, list[str]]:
    if path is None or not path.is_file():
        return False, False, None, ["global_hold_state_missing"]
    doc = _read_json(path, "global_hold_state")
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc.get("schema_version") != 1:
        raise SnapshotError("global_hold_state_invalid")
    hold = doc.get("global_hold")
    if not isinstance(hold, bool):
        raise SnapshotError("global_hold_flag_invalid")
    if not isinstance(doc.get("source"), str) or not doc["source"].strip():
        raise SnapshotError("global_hold_source_missing")
    age = _freshness(doc.get("observed_at"), now, "global_hold")
    reasons = ["global_hold_active"] if hold else []
    return True, hold, age, reasons


def _validate_budget(path: Path | None, now: datetime) -> tuple[bool, dict[str, Any], int | None, list[str]]:
    if path is None or not path.is_file():
        return False, {
            "limit_minutes": HARD_BUDGET_MINUTES,
            "consumed_minutes": None,
            "reserved_minutes": None,
            "remaining_minutes": None,
        }, None, ["budget_evidence_missing"]
    doc = _read_json(path, "budget_evidence")
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc.get("schema_version") != 1:
        raise SnapshotError("budget_evidence_invalid")
    if not isinstance(doc.get("source"), str) or not doc["source"].strip():
        raise SnapshotError("budget_source_missing")
    limit = doc.get("limit_minutes")
    consumed = doc.get("consumed_minutes")
    reserved = doc.get("reserved_minutes")
    for key, value in (("limit", limit), ("consumed", consumed), ("reserved", reserved)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SnapshotError(f"budget_{key}_invalid")
    if limit != HARD_BUDGET_MINUTES or consumed > limit or reserved > limit or consumed + reserved > limit:
        raise SnapshotError("budget_accounting_invalid")
    age = _freshness(doc.get("observed_at"), now, "budget")
    return True, {
        "limit_minutes": limit,
        "consumed_minutes": consumed,
        "reserved_minutes": reserved,
        "remaining_minutes": limit - consumed - reserved,
    }, age, []


def build_live_snapshot(
    queue: Any,
    catalog: Any,
    durable_state: Any,
    *,
    queue_sha256: str = "",
    catalog_sha256: str = "",
    state_sha256: str = "",
    hold_state_path: Path | None = None,
    budget_evidence_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a bounded read-only snapshot; never authorizes execution."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise SnapshotError("snapshot_clock_timezone_missing")
    queue_map = _id_map(queue, "runtime_queue")
    catalog_map = _id_map(catalog, "task_catalog")
    completed, recovery_tasks = _validate_state(durable_state)

    for task_id, queued in queue_map.items():
        catalog_task = catalog_map.get(task_id)
        if catalog_task is None:
            raise SnapshotError("queue_task_missing_from_catalog")
        for field in ("instruction", "allowed_paths"):
            if queued.get(field) != catalog_task.get(field):
                raise SnapshotError("queue_catalog_definition_mismatch")

    catalog_states: dict[str, str] = {}
    for task_id in catalog_map:
        recovery = recovery_tasks.get(task_id, {})
        if recovery.get("held") is True:
            state = "held"
        elif task_id in completed:
            state = "completed"
        elif recovery.get("resume_requires_review") is True:
            state = "review_required"
        else:
            state = "pending"
        catalog_states[task_id] = state

    queue_rows = []
    potential_candidate_ids = []
    for task_id, task in queue_map.items():
        state = catalog_states[task_id]
        if state == "pending":
            potential_candidate_ids.append(task_id)
        queue_rows.append({
            "id": task_id,
            "state": state,
            "allowed_paths": list(task.get("allowed_paths", []))
            if isinstance(task.get("allowed_paths", []), list) else [],
            "approval_claimed": task.get("execution_approved") is True,
            "approval_evidence_verified": False,
            "resume_requires_review": recovery_tasks.get(task_id, {}).get("resume_requires_review") is True,
        })

    hold_verified, global_hold, hold_age, hold_reasons = _validate_hold(hold_state_path, now)
    budget_verified, budget, budget_age, budget_reasons = _validate_budget(budget_evidence_path, now)
    reasons = list(hold_reasons) + list(budget_reasons)
    if global_hold:
        reasons.append("global_hold_active")
    if potential_candidate_ids:
        reasons.append("approval_evidence_unverified")
    else:
        reasons.append("no_eligible_queue_tasks")

    hard_blockers = set(hold_reasons + budget_reasons)
    if global_hold:
        hard_blockers.add("global_hold_active")
    # Candidate IDs are exposed only after the independent HOLD and budget
    # evidence gates pass. Pending tasks remain visible in the task table.
    candidate_ids = [] if hard_blockers else sorted(potential_candidate_ids)
    if hard_blockers:
        status = "BLOCKED"
    elif candidate_ids:
        status = "PLAN_READY"
    else:
        status = "NO_TASK"

    return {
        "schema_version": 1,
        "status": status,
        "sources": {
            "runtime_queue_sha256": queue_sha256,
            "task_catalog_sha256": catalog_sha256,
            "durable_state_sha256": state_sha256,
            "runtime_queue_count": len(queue_map),
            "catalog_count": len(catalog_map),
            "catalog_completed_count": sum(x == "completed" for x in catalog_states.values()),
            "catalog_held_count": sum(x == "held" for x in catalog_states.values()),
            "catalog_review_required_count": sum(
                entry.get("resume_requires_review") is True
                for entry in recovery_tasks.values()
                if isinstance(entry, dict)
            ),
            "catalog_pending_count": sum(x == "pending" for x in catalog_states.values()),
            "durable_completed_count": len(completed),
            "recovery_task_count": len(recovery_tasks),
        },
        "global_hold": {
            "verified": hold_verified,
            "active": global_hold if hold_verified else None,
            "age_seconds": hold_age,
        },
        "budget": {
            **budget,
            "verified": budget_verified,
            "age_seconds": budget_age,
        },
        "tasks": sorted(queue_rows, key=lambda row: row["id"]),
        "candidate_ids": sorted(candidate_ids),
        "execution_authorized": False,
        "approval_evidence_verified": False,
        "budget_evidence_verified": budget_verified,
        "execution_performed": False,
        "dispatch_performed": False,
        "repository_modified": False,
        "push_performed": False,
        "pull_request_created": False,
        "merge_performed": False,
        "deployment_performed": False,
        "reasons": sorted(set(reasons)),
    }


def build_snapshot_from_paths(
    queue_path: Path,
    catalog_path: Path,
    state_path: Path,
    *,
    hold_state_path: Path | None = None,
    budget_evidence_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    queue = _read_json(queue_path, "runtime_queue")
    catalog = _read_json(catalog_path, "task_catalog")
    state = _read_json(state_path, "durable_state")
    return build_live_snapshot(
        queue, catalog, state,
        queue_sha256=_sha256(queue_path),
        catalog_sha256=_sha256(catalog_path),
        state_sha256=_sha256(state_path),
        hold_state_path=hold_state_path,
        budget_evidence_path=budget_evidence_path,
        now=now,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--hold-state", type=Path)
    parser.add_argument("--budget-evidence", type=Path)
    args = parser.parse_args()
    try:
        result = build_snapshot_from_paths(
            args.queue, args.catalog, args.state,
            hold_state_path=args.hold_state,
            budget_evidence_path=args.budget_evidence,
        )
    except (OSError, SnapshotError) as exc:
        result = {
            "schema_version": 1,
            "status": "BLOCKED",
            "execution_authorized": False,
            "execution_performed": False,
            "dispatch_performed": False,
            "repository_modified": False,
            "reasons": [str(exc)[:160]],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0 if result["status"] in {"PLAN_READY", "NO_TASK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
