"""Deterministic, fail-closed next-task selection for the Control Tower.

This module only returns a decision record. It never executes a task, mutates
queues/state, approves model output, or grants merge/deploy rights.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

from core.control_tower_decision import ControlTowerDecisionRecord

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def select_next_task(
    queued_task_ids: Sequence[str],
    registered_task_ids: Collection[str],
    completed_task_ids: Collection[str],
    held_task_ids: Collection[str],
    *,
    evidence_sha: str,
    current_head_sha: str,
) -> ControlTowerDecisionRecord:
    """Select the first eligible registered queue item, or fail closed.

    Queue order is preserved. Every ID in every supplied state collection must
    use the canonical task-ID format. Every queued ID must be registered,
    including IDs already marked completed or held. Evidence must match HEAD.
    """
    if not isinstance(queued_task_ids, Sequence) or isinstance(queued_task_ids, (str, bytes)):
        return _blocked("invalid_state")
    if not _valid_collection(registered_task_ids) or not _valid_collection(completed_task_ids) or not _valid_collection(held_task_ids):
        return _blocked("invalid_state")
    if any(not _valid_task_id(item) for item in queued_task_ids):
        return _blocked("invalid_state")
    if len(set(queued_task_ids)) != len(queued_task_ids):
        return _blocked("duplicate_task")
    if (
        not isinstance(evidence_sha, str)
        or not isinstance(current_head_sha, str)
        or not _SHA_RE.fullmatch(evidence_sha)
        or not _SHA_RE.fullmatch(current_head_sha)
    ):
        return _blocked("invalid_state")
    if evidence_sha != current_head_sha:
        return _blocked("policy_blocked")
    if not queued_task_ids:
        return ControlTowerDecisionRecord(
            reason_code="queue_empty",
            confidence=1.0,
            priority=0,
            next_action="NOT_RUN",
            gate_status="NOT_RUN",
            evidence_sha=evidence_sha,
        )

    registered = set(registered_task_ids)
    completed = set(completed_task_ids)
    held = set(held_task_ids)
    # Validate the whole queue before selecting anything. Completed/held status
    # must never be used to excuse a queue entry absent from the registry.
    if any(task_id not in registered for task_id in queued_task_ids):
        return _blocked("policy_blocked")

    for task_id in queued_task_ids:
        if task_id in held or task_id in completed:
            continue
        return ControlTowerDecisionRecord(
            reason_code="evidence_sufficient",
            confidence=1.0,
            priority=50,
            next_action="SELECT_REGISTERED_TASK",
            gate_status="PASS",
            evidence_sha=evidence_sha,
            task_template_id=task_id,
        )

    remaining = [task_id for task_id in queued_task_ids if task_id not in completed]
    if remaining and all(task_id in held for task_id in remaining):
        return _blocked("task_held")
    return ControlTowerDecisionRecord(
        reason_code="no_eligible_task",
        confidence=1.0,
        priority=0,
        next_action="NOT_RUN",
        gate_status="NOT_RUN",
        evidence_sha=evidence_sha,
    )


def _valid_task_id(value: object) -> bool:
    return isinstance(value, str) and _TASK_ID_RE.fullmatch(value) is not None


def _valid_collection(value: object) -> bool:
    return (
        isinstance(value, Collection)
        and not isinstance(value, (str, bytes, Mapping))
        and all(_valid_task_id(item) for item in value)
    )


def _blocked(reason: str) -> ControlTowerDecisionRecord:
    return ControlTowerDecisionRecord(
        reason_code=reason,
        confidence=0.0,
        priority=0,
        next_action="HOLD",
        gate_status="BLOCKED",
    )


__all__ = ["select_next_task"]
