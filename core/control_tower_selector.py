"""Deterministic, fail-closed selector for registered autonomous-loop tasks.

This selector emits a non-authoritative decision record only. It does not
execute tasks, clear Recovery AI holds, mutate repositories, or authorize
publishing. Callers must re-read state and verify HEAD before launch.
"""
from __future__ import annotations

from collections.abc import Collection

from .control_tower_decision import ControlTowerDecisionRecord


def _decision(
    reason: str,
    *,
    action: str = "HOLD",
    gate: str = "BLOCKED",
) -> ControlTowerDecisionRecord:
    return ControlTowerDecisionRecord(
        reason_code=reason,
        confidence=1.0 if reason == "queue_empty" else 0.0,
        priority=0,
        next_action=action,
        gate_status=gate,
    )


def _valid_ids(value: object) -> bool:
    return isinstance(value, (list, tuple)) and all(
        isinstance(item, str) and bool(item.strip()) and item == item.strip()
        for item in value
    )


def select_next_task(
    queued_task_ids: list[str],
    registered_task_ids: list[str],
    completed_task_ids: Collection[str],
    held_task_ids: Collection[str],
    *,
    evidence_sha: str,
    current_head_sha: str,
) -> ControlTowerDecisionRecord:
    """Choose the first registered queued task that is neither completed nor held.

    Malformed state, duplicate queue entries, stale evidence, or ambiguous
    collection types result in HOLD/BLOCKED. An empty queue is explicitly
    NOT_RUN, never PASS. Unknown queued IDs are never selected.
    """
    if (
        not _valid_ids(queued_task_ids)
        or not _valid_ids(registered_task_ids)
        or not isinstance(completed_task_ids, Collection)
        or isinstance(completed_task_ids, (str, bytes))
        or not isinstance(held_task_ids, Collection)
        or isinstance(held_task_ids, (str, bytes))
        or not all(isinstance(item, str) and item and item == item.strip() for item in completed_task_ids)
        or not all(isinstance(item, str) and item and item == item.strip() for item in held_task_ids)
        or not isinstance(evidence_sha, str)
        or not isinstance(current_head_sha, str)
        or len(evidence_sha) != 40
        or len(current_head_sha) != 40
        or any(ch not in "0123456789abcdef" for ch in evidence_sha)
        or any(ch not in "0123456789abcdef" for ch in current_head_sha)
    ):
        return _decision("invalid_state")

    if evidence_sha != current_head_sha:
        return _decision("policy_blocked")

    if not queued_task_ids:
        return _decision("queue_empty", action="NOT_RUN", gate="NOT_RUN")

    if len(set(queued_task_ids)) != len(queued_task_ids):
        return _decision("duplicate_task")

    registered = set(registered_task_ids)
    completed = set(completed_task_ids)
    held = set(held_task_ids)

    # A completed ID reappearing in the queue is stale/duplicate state. Stop
    # instead of silently trusting mutable queue state.
    if any(task_id in completed for task_id in queued_task_ids):
        return _decision("duplicate_task")

    registered_in_queue = [task_id for task_id in queued_task_ids if task_id in registered]
    if not registered_in_queue:
        return _decision("unregistered_task")

    for task_id in registered_in_queue:
        if task_id in held:
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

    return _decision("task_held")


__all__ = ["select_next_task"]
