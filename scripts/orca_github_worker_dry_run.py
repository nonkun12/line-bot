"""Single-task, side-effect-free worker dry-run for Orca Phase 3-B.

This module validates a claimed task envelope and emits a deterministic report.
It deliberately has no subprocess, HTTP, GitHub, filesystem-write, or dispatch
implementation. A successful report is not task execution authorization.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from scripts.orca_github_task_queue import QueueRejected, _time, _validate
from scripts.orca_github_emergency_stop import require_not_stopped
from scripts.orca_github_runaway_guard import validate_worker_start
from scripts.orca_github_task_registry import TaskContractRejected, validate_typed_task


MAX_PAYLOAD_BYTES = 64 * 1024
_ENVELOPE_KEYS = {"task_id", "request_hash", "owner", "run_id", "payload"}


class WorkerDryRunRejected(ValueError):
    """Raised when a task cannot safely enter the dry-run worker."""


def dry_run_one(*, queue_state: Any, envelope: Any, now: datetime) -> dict[str, Any]:
    """Validate exactly one claimed task and return a no-side-effect report."""
    try:
        _validate(queue_state)
    except (QueueRejected, TypeError, AttributeError) as exc:
        raise WorkerDryRunRejected(f"queue_state_invalid:{exc}") from None

    try:
        require_not_stopped(queue_state)
    except ValueError as exc:
        raise WorkerDryRunRejected(str(exc)) from None
    if queue_state.get("global_hold") is not False:
        raise WorkerDryRunRejected("global_hold_active_or_unverifiable")
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS:
        raise WorkerDryRunRejected("worker_envelope_shape_invalid")
    for key in ("task_id", "request_hash", "owner", "run_id"):
        if not isinstance(envelope.get(key), str) or not envelope[key]:
            raise WorkerDryRunRejected(f"worker_envelope_{key}_invalid")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise WorkerDryRunRejected("worker_payload_invalid")
    try:
        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WorkerDryRunRejected("worker_payload_not_canonical_json") from None
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        raise WorkerDryRunRejected("worker_payload_too_large")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if digest != envelope["request_hash"]:
        raise WorkerDryRunRejected("worker_payload_hash_mismatch")

    try:
        task_contract = validate_typed_task(task_id=envelope["task_id"], payload=payload)
    except TaskContractRejected as exc:
        raise WorkerDryRunRejected(f"typed_task_rejected:{exc}") from None

    task_matches = [
        task for task in queue_state["tasks"]
        if task["task_id"] == envelope["task_id"]
    ]
    if len(task_matches) != 1:
        raise WorkerDryRunRejected("worker_task_missing_or_ambiguous")
    task = task_matches[0]
    if task.get("status") != "claimed":
        raise WorkerDryRunRejected("worker_task_not_claimed")
    if task.get("request_hash") != digest:
        raise WorkerDryRunRejected("worker_task_hash_mismatch")

    lease = queue_state.get("active_lease")
    if not isinstance(lease, dict):
        raise WorkerDryRunRejected("worker_lease_missing")
    if (lease.get("task_id"), lease.get("owner"), lease.get("run_id")) != (
        envelope["task_id"], envelope["owner"], envelope["run_id"]
    ):
        raise WorkerDryRunRejected("worker_lease_owner_or_run_mismatch")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise WorkerDryRunRejected("worker_clock_timezone_missing")
    current = now.astimezone(timezone.utc)
    try:
        validate_worker_start(
            state=queue_state, task_id=envelope["task_id"],
            run_id=envelope["run_id"], now=now,
        )
    except ValueError as exc:
        raise WorkerDryRunRejected(f"runaway_guard_blocked:{exc}") from None
    if current >= _time(lease.get("expires_at")):
        raise WorkerDryRunRejected("worker_lease_expired")

    return {
        "status": "DRY_RUN_PASS",
        "task_id": envelope["task_id"],
        "request_hash": digest,
        "payload_bytes": len(payload_bytes),
        "lease_expires_at": lease["expires_at"],
        "side_effects_performed": False,
        "execution_started": False,
        "task_contract": task_contract,
        "execution_supported": False,
        "required_next_action": "implement_and_review_a_dedicated_handler_before_dispatch",
    }
