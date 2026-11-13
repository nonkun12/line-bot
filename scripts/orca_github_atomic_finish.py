"""Atomic persistence boundary for one Orca task outcome.

The queue terminal status, lease release, failure counter/cooldown and outcome
replay ledger are derived as one state snapshot and committed with one CAS.
This module records outcomes only; it never executes or dispatches task code.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.orca_github_runaway_guard import (
    RunawayGuardRejected,
    finish_with_outcome,
)
from scripts.orca_github_state_store import StateSnapshot


def persist_task_outcome(
    *,
    store: Any,
    snapshot: StateSnapshot,
    task_id: str,
    owner: str,
    run_id: str,
    now: datetime,
    outcome: str,
) -> dict[str, Any]:
    """Atomically persist terminal outcome and release the active lease.

    A repeated identical terminal outcome is returned without a second write.
    Conflicting/stale results fail closed. STOP/HOLD are intentionally not
    cleared or bypassed; recording a result is bookkeeping, not execution.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RunawayGuardRejected("outcome_clock_timezone_missing")
    next_state = finish_with_outcome(
        state=snapshot.state,
        expected_revision=snapshot.state.get("revision"),
        task_id=task_id,
        owner=owner,
        run_id=run_id,
        now=now.isoformat(),
        outcome=outcome,
    )
    if next_state == snapshot.state:
        return {
            "status": "ALREADY_RECORDED",
            "task_id": task_id,
            "outcome": outcome,
            "snapshot": snapshot,
            "persisted": False,
            "execution_started": False,
        }
    persisted = store.write(
        snapshot=snapshot,
        next_state=next_state,
        expected_revision=snapshot.state["revision"],
    )
    return {
        "status": "RECORDED",
        "task_id": task_id,
        "outcome": outcome,
        "snapshot": persisted,
        "persisted": True,
        "execution_started": False,
    }
