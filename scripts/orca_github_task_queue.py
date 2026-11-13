"""Pure state machine for a GitHub-native single-worker task queue.

Persistence is deliberately separate: callers MUST serialize writers and commit
updates using a non-force fast-forward ref update from the exact state revision.
This module alone is not a durable or atomic queue backend.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from typing import Any

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_STATES = {"queued", "claimed", "done", "failed"}


class QueueRejected(ValueError):
    """Raised when a queue transition is unsafe or inconsistent."""


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise QueueRejected("timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QueueRejected("timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise QueueRejected("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_state() -> dict[str, Any]:
    return {"schema_version": 1, "revision": 0, "global_hold": True,
            "emergency_stop": False, "emergency_stop_event": None,
            "tasks": [], "active_lease": None, "consumed_approval_ids": []}


def _validate(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise QueueRejected("queue_state_missing_or_invalid")
    if isinstance(state.get("revision"), bool) or not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise QueueRejected("queue_revision_invalid")
    if not isinstance(state.get("global_hold"), bool):
        raise QueueRejected("global_hold_missing_or_invalid")
    if not isinstance(state.get("emergency_stop"), bool):
        raise QueueRejected("emergency_stop_missing_or_invalid")
    if not isinstance(state.get("tasks"), list):
        raise QueueRejected("queue_tasks_invalid")
    consumed = state.get("consumed_approval_ids")
    if (not isinstance(consumed, list)
            or any(not isinstance(value, str) or not _HEX_64.fullmatch(value) for value in consumed)
            or len(consumed) != len(set(consumed))):
        raise QueueRejected("approval_replay_ledger_invalid")
    ids = set()
    claimed = []
    for task in state["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("task_id"), str) or not task["task_id"]:
            raise QueueRejected("task_identity_invalid")
        if task["task_id"] in ids:
            raise QueueRejected("duplicate_task_id")
        ids.add(task["task_id"])
        if task.get("status") not in _STATES:
            raise QueueRejected("task_status_invalid")
        if not _HEX_64.fullmatch(str(task.get("request_hash", ""))):
            raise QueueRejected("task_request_hash_invalid")
        if task["status"] == "claimed":
            claimed.append(task["task_id"])
    lease = state.get("active_lease")
    if len(claimed) > 1:
        raise QueueRejected("multiple_claimed_tasks")
    if (lease is None) != (len(claimed) == 0):
        raise QueueRejected("lease_task_state_mismatch")
    if lease is not None:
        if not isinstance(lease, dict) or lease.get("task_id") != claimed[0]:
            raise QueueRejected("lease_identity_mismatch")
        if not all(isinstance(lease.get(k), str) and lease[k] for k in ("owner", "run_id", "expires_at")):
            raise QueueRejected("lease_fields_missing")
        _time(lease["expires_at"])
    return state


def _revision(state: dict[str, Any], expected_revision: int) -> None:
    if isinstance(expected_revision, bool) or expected_revision != state["revision"]:
        raise QueueRejected("stale_revision_conflict")


def enqueue(state: dict[str, Any], *, expected_revision: int, task_id: str,
            request_hash: str, approved: bool, created_at: str) -> dict[str, Any]:
    _validate(state)
    _revision(state, expected_revision)
    if approved is not True:
        raise QueueRejected("explicit_approval_required")
    if not isinstance(task_id, str) or not task_id or not _HEX_64.fullmatch(request_hash or ""):
        raise QueueRejected("task_identity_or_hash_invalid")
    if any(t["task_id"] == task_id for t in state["tasks"]):
        raise QueueRejected("duplicate_task_id")
    created = _time(created_at)
    out = copy.deepcopy(state)
    out["tasks"].append({"task_id": task_id, "request_hash": request_hash,
                         "status": "queued", "created_at": _iso(created)})
    out["revision"] += 1
    return _validate(out)


def claim_next(state: dict[str, Any], *, expected_revision: int, owner: str,
               run_id: str, now: str, lease_seconds: int = 600) -> dict[str, Any]:
    _validate(state)
    _revision(state, expected_revision)
    if state["emergency_stop"]:
        raise QueueRejected("emergency_stop_active")
    if state["global_hold"]:
        raise QueueRejected("global_hold_active")
    if state["active_lease"] is not None:
        raise QueueRejected("worker_already_has_active_lease")
    if not owner or not run_id or isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 3600:
        raise QueueRejected("claim_parameters_invalid")
    current = _time(now)
    queued = sorted((t for t in state["tasks"] if t["status"] == "queued"),
                    key=lambda t: (t["created_at"], t["task_id"]))
    if not queued:
        raise QueueRejected("queue_empty")
    task = queued[0]
    out = copy.deepcopy(state)
    task_out = next(t for t in out["tasks"] if t["task_id"] == task["task_id"])
    task_out["status"] = "claimed"
    out["active_lease"] = {"task_id": task["task_id"], "owner": owner,
                           "run_id": run_id,
                           "expires_at": _iso(current + timedelta(seconds=lease_seconds))}
    out["revision"] += 1
    return _validate(out)


def finish(state: dict[str, Any], *, expected_revision: int, task_id: str,
           owner: str, run_id: str, now: str, outcome: str) -> dict[str, Any]:
    _validate(state)
    _revision(state, expected_revision)
    if outcome not in {"done", "failed"}:
        raise QueueRejected("outcome_invalid")
    lease = state["active_lease"]
    if lease is None or (lease["task_id"], lease["owner"], lease["run_id"]) != (task_id, owner, run_id):
        raise QueueRejected("lease_owner_mismatch")
    if _time(now) >= _time(lease["expires_at"]):
        raise QueueRejected("lease_expired")
    out = copy.deepcopy(state)
    next(t for t in out["tasks"] if t["task_id"] == task_id)["status"] = outcome
    out["active_lease"] = None
    out["revision"] += 1
    return _validate(out)


def reclaim_expired(state: dict[str, Any], *, expected_revision: int, now: str) -> dict[str, Any]:
    _validate(state)
    _revision(state, expected_revision)
    lease = state["active_lease"]
    if lease is None or _time(now) < _time(lease["expires_at"]):
        raise QueueRejected("no_expired_lease")
    out = copy.deepcopy(state)
    next(t for t in out["tasks"] if t["task_id"] == lease["task_id"])["status"] = "queued"
    out["active_lease"] = None
    out["revision"] += 1
    return _validate(out)
