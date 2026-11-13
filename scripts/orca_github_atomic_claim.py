"""Atomic approval-consumption + single-task claim coordinator.

The coordinator validates the full Phase 3-A gate, adds the approval replay
marker, claims one task, and persists both changes in one non-force state-store
commit. It never executes task code or dispatches a worker.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Iterable

from scripts.orca_github_execution_gate import evaluate_execution_gate
from scripts.orca_github_state_store import StateSnapshot
from scripts.orca_github_task_queue import claim_next
from scripts.orca_github_runaway_guard import validate_and_consume_claim
from scripts.orca_github_emergency_stop import require_not_stopped


def authorize_and_claim_one(
    *,
    store: Any,
    snapshot: StateSnapshot,
    repository: str,
    task_id: str,
    request_hash: str,
    approval: Any,
    approval_signing_key: str,
    allowed_approvers: Iterable[str],
    budget_evidence: Any,
    budget_signing_key: str,
    billing_account_id: str,
    improvement_cycle: Any,
    now: datetime,
    owner: str,
    run_id: str,
    lease_seconds: int = 600,
) -> dict[str, Any]:
    """Persist one approval marker and one lease with a single CAS write.

    Any gate rejection or stale-ref conflict aborts before a task can be
    claimed. The returned snapshot is durable state; this function does not
    invoke the task, create a process, or make a network dispatch.
    """
    state = snapshot.state
    require_not_stopped(state)
    gate = evaluate_execution_gate(
        repository=repository,
        queue_state=state,
        task_id=task_id,
        request_hash=request_hash,
        approval=approval,
        approval_signing_key=approval_signing_key,
        allowed_approvers=allowed_approvers,
        consumed_approval_ids=state.get("consumed_approval_ids"),
        budget_evidence=budget_evidence,
        budget_signing_key=budget_signing_key,
        billing_account_id=billing_account_id,
        improvement_cycle=improvement_cycle,
        now=now,
    )
    if gate.get("status") != "PASS" or gate.get("execution_enabled") is not False:
        raise RuntimeError("execution_gate_did_not_return_non_executing_pass")
    approval_id = gate.get("consume_approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        raise RuntimeError("execution_gate_approval_marker_missing")

    # Enforce durable hard caps before any claim; consume the run slot in the
    # same CAS write as the replay marker and lease.
    next_state = copy.deepcopy(state)
    next_state["run_guard"] = validate_and_consume_claim(
        state=state, task_id=task_id, now=now,
    )
    ledger = next_state.get("consumed_approval_ids")
    if not isinstance(ledger, list) or approval_id in ledger:
        raise RuntimeError("approval_replay_detected_before_claim")
    ledger.append(approval_id)
    claimed_state = claim_next(
        next_state,
        expected_revision=state["revision"],
        owner=owner,
        run_id=run_id,
        now=now.isoformat(),
        lease_seconds=lease_seconds,
    )
    # One state-store write commits the replay marker and lease together.
    persisted = store.write(
        snapshot=snapshot,
        next_state=claimed_state,
        expected_revision=state["revision"],
    )
    return {
        "status": "CLAIMED",
        "task_id": task_id,
        "approval_id": approval_id,
        "lease": persisted.state.get("active_lease"),
        "snapshot": persisted,
        "execution_started": False,
        "required_next_action": "worker_may_start_only_after_separate_runtime_checks",
    }
