"""Fail-closed decision policy for bounded autonomous-loop recovery.

This module is deliberately pure: it does not call GitHub, mutate state, or
dispatch workflows. Callers must persist the slot decision atomically before
dispatching and must fail closed when persistence or API evidence is uncertain.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
INVALID_TASK_IDS = {"", "NOT_RUN", "QUEUE_EMPTY", "QUEUE_EXHAUSTED_NO_TASKS"}


class RecoveryClass(StrEnum):
    MISSING_RUN = "MISSING_RUN"
    RUN_STILL_ACTIVE = "RUN_STILL_ACTIVE"
    QUEUE_EMPTY = "QUEUE_EMPTY"
    NOT_RUN = "NOT_RUN"
    TASK_FAILED = "TASK_FAILED"
    BLOCKED_HELD = "BLOCKED_HELD"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    DUPLICATE_SLOT = "DUPLICATE_SLOT"


class RecoveryAction(StrEnum):
    DISPATCH_ONE_TASK = "DISPATCH_ONE_TASK"
    NO_ACTION = "NO_ACTION"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RecoveryDecision:
    classification: RecoveryClass
    action: RecoveryAction
    reason: str


def decide_recovery(
    *, run_status: str | None, run_conclusion: str | None = None,
    task_id: str | None = None, safety_gate: str | None = None,
    verification: str | None = None, tests: str | None = None,
    held: bool = False, slot_already_dispatched: bool = False,
    another_run_active: bool = False, evidence_available: bool = True,
) -> RecoveryDecision:
    """Return a deterministic recovery decision; uncertainty never dispatches."""
    if not evidence_available:
        return RecoveryDecision(RecoveryClass.AUDIT_UNAVAILABLE, RecoveryAction.BLOCK,
                                "required GitHub/Sheets evidence unavailable")
    if slot_already_dispatched:
        return RecoveryDecision(RecoveryClass.DUPLICATE_SLOT, RecoveryAction.NO_ACTION,
                                "recovery already attempted for this schedule slot")
    if another_run_active or run_status in {"queued", "in_progress"}:
        return RecoveryDecision(RecoveryClass.RUN_STILL_ACTIVE, RecoveryAction.NO_ACTION,
                                "a distributed-loop run is active or its state is uncertain")
    if run_status is None:
        return RecoveryDecision(RecoveryClass.MISSING_RUN, RecoveryAction.DISPATCH_ONE_TASK,
                                "scheduled run missing; permit one bounded recovery dispatch")
    if run_status != "completed":
        return RecoveryDecision(RecoveryClass.AUDIT_UNAVAILABLE, RecoveryAction.BLOCK,
                                "unrecognized workflow run status")
    if run_conclusion != "success":
        return RecoveryDecision(RecoveryClass.WORKFLOW_FAILED, RecoveryAction.BLOCK,
                                "workflow failed; automatic rerun requires reviewed cause-fix evidence")

    normalized_id = (task_id or "").strip()
    normalized_token = re.sub(r"[^A-Z0-9]+", "_", normalized_id.upper()).strip("_")
    if normalized_token in {"QUEUE_EMPTY", "QUEUE_EXHAUSTED_NO_TASKS"}:
        return RecoveryDecision(RecoveryClass.QUEUE_EMPTY, RecoveryAction.NO_ACTION,
                                "queue is empty; refill or task-catalog review is required")
    if normalized_token in INVALID_TASK_IDS or not TASK_ID.fullmatch(normalized_id):
        return RecoveryDecision(RecoveryClass.NOT_RUN, RecoveryAction.NO_ACTION,
                                "no valid task execution evidence")
    if held:
        return RecoveryDecision(RecoveryClass.BLOCKED_HELD, RecoveryAction.BLOCK,
                                "held tasks require explicit cause-fixed confirmation")
    if (safety_gate or "").strip().upper() != "PASS":
        return RecoveryDecision(RecoveryClass.BLOCKED_HELD, RecoveryAction.BLOCK,
                                "safety gate is not PASS")
    if (verification or "").strip().upper() not in {"PASS", "NO_CHANGE"}:
        return RecoveryDecision(RecoveryClass.TASK_FAILED, RecoveryAction.BLOCK,
                                "verification is not successful; do not blindly rerun")
    if (tests or "").strip().upper() not in {"PASS", "NO_CHANGE"}:
        return RecoveryDecision(RecoveryClass.TASK_FAILED, RecoveryAction.BLOCK,
                                "tests are not successful; do not blindly rerun")
    return RecoveryDecision(RecoveryClass.VERIFIED_SUCCESS, RecoveryAction.NO_ACTION,
                            "task has valid passing safety and verification evidence")
