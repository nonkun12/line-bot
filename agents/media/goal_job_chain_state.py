"""Deterministic, resumable state derivation for audiovisual-to-game Goal job chains.

This module is a pure planning/state layer. It does not enqueue or execute jobs,
write checkpoints, bypass human gates, or modify assets.
"""
from __future__ import annotations

import re
from collections import deque
from copy import deepcopy
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MAX_STAGES = 40


def _validated_stages(plan: object) -> tuple[str, list[dict[str, Any]], list[str]]:
    if not isinstance(plan, dict) or plan.get("schema_version") != "audiovisual-to-game-sprint-plan.v1":
        raise ValueError("plan must use audiovisual-to-game-sprint-plan.v1")
    goal_id = plan.get("goal_id")
    stages = plan.get("stages")
    if not isinstance(goal_id, str) or not _ID.fullmatch(goal_id):
        raise ValueError("plan goal_id is invalid")
    if not isinstance(stages, list) or not 1 <= len(stages) <= _MAX_STAGES:
        raise ValueError("plan must contain 1..40 stages")

    by_id: dict[str, dict[str, Any]] = {}
    for raw in stages:
        if not isinstance(raw, dict):
            raise ValueError("each stage must be an object")
        sid = raw.get("job_id")
        deps = raw.get("depends_on")
        gate = raw.get("human_gate")
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in by_id:
            raise ValueError("stage job_ids must be valid and unique")
        if not isinstance(deps, list) or any(not isinstance(dep, str) or not _ID.fullmatch(dep) for dep in deps):
            raise ValueError(f"stage {sid} has invalid dependencies")
        if len(deps) != len(set(deps)) or sid in deps:
            raise ValueError(f"stage {sid} has duplicate or self dependency")
        if gate is not None and (not isinstance(gate, str) or not gate.strip() or len(gate) > 120):
            raise ValueError(f"stage {sid} has invalid human_gate")
        by_id[sid] = deepcopy(raw)

    for sid, stage in by_id.items():
        if any(dep not in by_id for dep in stage["depends_on"]):
            raise ValueError(f"stage {sid} references an unknown dependency")

    # Stable Kahn ordering detects cycles and makes readiness deterministic.
    indegree = {sid: len(stage["depends_on"]) for sid, stage in by_id.items()}
    children = {sid: [] for sid in by_id}
    for sid, stage in by_id.items():
        for dep in stage["depends_on"]:
            children[dep].append(sid)
    queue = deque(sid for sid in by_id if indegree[sid] == 0)
    order: list[str] = []
    while queue:
        sid = queue.popleft()
        order.append(sid)
        for child in children[sid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(by_id):
        raise ValueError("sprint plan contains a dependency cycle")
    return goal_id, list(by_id.values()), order


def derive_goal_job_chain_state(
    plan: object,
    *,
    completed_job_ids: object = (),
    approved_gate_job_ids: object = (),
    held_job_ids: object = (),
) -> dict[str, Any]:
    """Derive READY/BLOCKED/HOLD/approval states from durable caller evidence.

    A human gate belongs to the stage that produced the reviewed artifact. The
    stage may complete, but its dependents remain blocked until its gate is
    explicitly approved. HOLD propagates to all descendants.
    """
    goal_id, stages, order = _validated_stages(plan)
    known = set(order)

    def ids(value: object, label: str) -> set[str]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError(f"{label} must be a collection of stage IDs")
        result = set(value)
        if any(not isinstance(item, str) or item not in known for item in result):
            raise ValueError(f"{label} contains an unknown stage ID")
        return result

    completed = ids(completed_job_ids, "completed_job_ids")
    approved = ids(approved_gate_job_ids, "approved_gate_job_ids")
    held = ids(held_job_ids, "held_job_ids")
    by_id = {stage["job_id"]: stage for stage in stages}
    for sid in approved:
        if by_id[sid].get("human_gate") is None:
            raise ValueError(f"stage {sid} has no human gate to approve")
        if sid not in completed:
            raise ValueError(f"stage {sid} cannot be approved before completion")
    if completed & held:
        raise ValueError("a stage cannot be both completed and held")

    state: dict[str, str] = {}
    for sid in order:
        stage = by_id[sid]
        if sid in held or any(state[dep] == "HOLD" for dep in stage["depends_on"]):
            state[sid] = "HOLD"
        elif sid in completed:
            if not all(state[dep] == "COMPLETED" for dep in stage["depends_on"]):
                raise ValueError(f"completed stage {sid} has incomplete or unapproved dependencies")
            if stage.get("human_gate") and sid not in approved:
                state[sid] = "AWAITING_HUMAN_APPROVAL"
            else:
                state[sid] = "COMPLETED"
        elif all(state[dep] == "COMPLETED" for dep in stage["depends_on"]):
            state[sid] = "READY"
        else:
            state[sid] = "BLOCKED"

    ready = [sid for sid in order if state[sid] == "READY"]
    return {
        "schema_version": "goal-job-chain-state.v1",
        "goal_id": goal_id,
        "state": state,
        "ready_job_ids": ready,
        "completed_job_ids": [sid for sid in order if state[sid] == "COMPLETED"],
        "awaiting_human_approval_job_ids": [
            sid for sid in order if state[sid] == "AWAITING_HUMAN_APPROVAL"
        ],
        "held_job_ids": [sid for sid in order if state[sid] == "HOLD"],
        "snapshot": {
            "completed_job_ids": [sid for sid in order if sid in completed],
            "approved_gate_job_ids": [sid for sid in order if sid in approved],
            "held_job_ids": [sid for sid in order if sid in held],
        },
        "permissions": {
            "enqueue_jobs": False,
            "execute_jobs": False,
            "approve_human_gates": False,
            "clear_hold": False,
            "modify_assets": False,
            "publish": False,
            "merge": False,
            "deploy": False,
        },
    }


__all__ = ["derive_goal_job_chain_state"]
