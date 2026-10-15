"""Fail-closed adapter between the Control Tower contract and the distributed loop.

Only exact, pre-registered task definitions may pass this deterministic policy
gate. This does not treat model output as approval and grants no merge/deploy
rights. The current HEAD is captured immediately before each task is launched.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from core.control_tower_decision import ControlTowerDecisionRecord

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def authorize_registered_task(
    task: object,
    registered_tasks: Sequence[dict[str, Any]],
    current_head_sha: str,
) -> tuple[bool, str]:
    """Authorize only an exact catalog entry against the current repository HEAD."""
    if not isinstance(current_head_sha, str) or not _SHA_RE.fullmatch(current_head_sha):
        return False, "invalid_current_head_sha"
    if not isinstance(task, dict) or not isinstance(registered_tasks, Sequence):
        return False, "invalid_task_registry"
    if isinstance(registered_tasks, (str, bytes)):
        return False, "invalid_task_registry"

    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        return False, "invalid_task_id"

    matches = [item for item in registered_tasks if isinstance(item, dict) and item.get("id") == task_id]
    if len(matches) != 1:
        return False, "task_not_uniquely_registered"

    registered = matches[0]
    # Match the complete executable definition, not just the task ID.
    for field in ("id", "instruction", "allowed_paths"):
        if task.get(field) != registered.get(field):
            return False, "task_definition_mismatch"
    if not isinstance(task.get("instruction"), str) or not task["instruction"].strip():
        return False, "invalid_task_instruction"
    paths = task.get("allowed_paths")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) and path.strip() for path in paths
    ):
        return False, "invalid_allowed_paths"

    try:
        decision = ControlTowerDecisionRecord(
            reason_code="evidence_sufficient",
            confidence=1.0,
            priority=50,
            next_action="SELECT_REGISTERED_TASK",
            gate_status="PASS",
            evidence_sha=current_head_sha,
            task_template_id=task_id,
        )
    except (TypeError, ValueError):
        return False, "decision_contract_rejected"

    registered_ids = {item["id"] for item in registered_tasks if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if not decision.execution_eligible(registered_ids, current_head_sha):
        return False, "decision_not_eligible"
    return True, "registered_task_and_current_head_verified"


__all__ = ["authorize_registered_task"]
