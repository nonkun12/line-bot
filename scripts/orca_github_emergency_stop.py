"""Durable, human-triggered Emergency Stop for Orca.

The stop is latched in the same GitHub state-store CAS mechanism as queue
state. This module intentionally exposes no automatic clear operation.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from typing import Any

from scripts.orca_github_state_store import StateSnapshot


class EmergencyStopRejected(ValueError):
    pass


def emergency_stop_active(state: Any) -> bool:
    # Missing state is treated as STOP, never as permission to proceed.
    return not isinstance(state, dict) or state.get("emergency_stop") is not False


def activate_emergency_stop(*, store: Any, snapshot: StateSnapshot,
                            requested_by: str, reason: str, event_id: str,
                            now: datetime, human_authorized: bool) -> dict[str, Any]:
    """Latch STOP using one non-force CAS write; no auto-clear is provided."""
    if human_authorized is not True:
        raise EmergencyStopRejected("human_authorization_required")
    if not all(isinstance(v, str) and v.strip() for v in (requested_by, reason, event_id)):
        raise EmergencyStopRejected("stop_audit_fields_required")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise EmergencyStopRejected("stop_clock_timezone_required")
    state = snapshot.state
    if not isinstance(state, dict):
        raise EmergencyStopRejected("state_snapshot_invalid")
    existing = state.get("emergency_stop_event")
    event_hash = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    if state.get("emergency_stop") is True:
        if isinstance(existing, dict) and existing.get("event_hash") == event_hash:
            return {"status": "ALREADY_STOPPED", "snapshot": snapshot, "write_performed": False}
        raise EmergencyStopRejected("emergency_stop_already_latched")
    if state.get("emergency_stop") is not False:
        raise EmergencyStopRejected("emergency_stop_state_missing_or_invalid")
    updated = copy.deepcopy(state)
    updated["emergency_stop"] = True
    updated["emergency_stop_event"] = {
        "event_hash": event_hash,
        "requested_by": requested_by,
        "reason": reason.strip()[:500],
        "activated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    updated["revision"] = state.get("revision", -1) + 1
    persisted = store.write(
        snapshot=snapshot, next_state=updated,
        expected_revision=state["revision"],
    )
    return {"status": "EMERGENCY_STOPPED", "snapshot": persisted, "write_performed": True}


def require_not_stopped(state: Any) -> None:
    if emergency_stop_active(state):
        raise EmergencyStopRejected("emergency_stop_active_or_unverifiable")
