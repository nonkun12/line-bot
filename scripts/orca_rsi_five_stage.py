"""Deterministic five-stage RSI cycle and fail-closed continuation gate.

This module is deliberately provider-free and side-effect-free. It does not
create patches, call models, dispatch workflows, or change repository state.
A trusted worker may use its result only after separately verifying all gates.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

RSI_STAGES = (
    "evaluate",
    "diagnose",
    "hypothesize",
    "experiment",
    "select_evolve",
)
FINAL_RESULTS = {"PASS", "FAIL", "NO_CHANGE", "BLOCKED"}
MAX_EVIDENCE_LENGTH = 2_000


class RSICycleRejected(ValueError):
    """Raised when a cycle transition is incomplete or out of order."""


def new_cycle(cycle_id: str) -> dict[str, Any]:
    """Create an empty five-stage cycle; this does not persist it."""
    if not isinstance(cycle_id, str) or not cycle_id.strip() or len(cycle_id) > 128:
        raise RSICycleRejected("cycle_id_invalid")
    return {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "completed_stages": [],
        "evidence": {},
        "result": None,
    }


def record_stage(
    cycle: Any,
    *,
    stage: str,
    evidence: str,
    result: str | None = None,
) -> dict[str, Any]:
    """Record exactly the next RSI stage and return a copied cycle."""
    if not isinstance(cycle, dict) or cycle.get("schema_version") != 1:
        raise RSICycleRejected("cycle_missing_or_invalid")
    if cycle.get("result") is not None:
        raise RSICycleRejected("cycle_already_finalized")
    completed = cycle.get("completed_stages")
    evidence_map = cycle.get("evidence")
    if (not isinstance(completed, list) or not isinstance(evidence_map, dict)
            or completed != list(RSI_STAGES[:len(completed)])):
        raise RSICycleRejected("cycle_stage_history_invalid")
    if len(completed) >= len(RSI_STAGES):
        raise RSICycleRejected("cycle_already_complete")
    expected = RSI_STAGES[len(completed)]
    if stage != expected:
        raise RSICycleRejected("rsi_stage_out_of_order")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > MAX_EVIDENCE_LENGTH:
        raise RSICycleRejected("rsi_stage_evidence_missing_or_invalid")

    if stage == "select_evolve":
        if result not in FINAL_RESULTS:
            raise RSICycleRejected("rsi_final_result_missing_or_invalid")
    elif result is not None:
        raise RSICycleRejected("rsi_result_only_allowed_at_select_evolve")

    updated = deepcopy(cycle)
    updated["completed_stages"].append(stage)
    updated["evidence"][stage] = evidence.strip()
    if stage == "select_evolve":
        updated["result"] = result
    return updated


def continuation_decision(
    cycle: Any,
    *,
    queue_has_pending: bool,
    global_hold: bool,
    emergency_stop: bool,
    budget_verified: bool,
    approval_verified: bool,
    independent_review_pass: bool,
    kill_switch: bool,
) -> dict[str, Any]:
    """Allow one bounded next cycle only when every independent gate passes."""
    reasons: list[str] = []
    if not isinstance(cycle, dict) or cycle.get("schema_version") != 1:
        reasons.append("cycle_missing_or_invalid")
    else:
        if not isinstance(cycle.get("cycle_id"), str) or not cycle["cycle_id"].strip():
            reasons.append("cycle_id_invalid")
        if cycle.get("completed_stages") != list(RSI_STAGES):
            reasons.append("rsi_cycle_incomplete")
        if cycle.get("result") != "PASS":
            reasons.append("rsi_result_not_pass")
        evidence = cycle.get("evidence")
        if (not isinstance(evidence, dict) or set(evidence) != set(RSI_STAGES)
                or any(not isinstance(evidence.get(stage), str) or not evidence[stage].strip()
                       for stage in RSI_STAGES)):
            reasons.append("rsi_evidence_incomplete")
    boolean_gates = {
        "queue_has_pending": queue_has_pending,
        "global_hold": global_hold,
        "emergency_stop": emergency_stop,
        "budget_verified": budget_verified,
        "approval_verified": approval_verified,
        "independent_review_pass": independent_review_pass,
        "kill_switch": kill_switch,
    }
    if any(type(value) is not bool for value in boolean_gates.values()):
        reasons.append("gate_input_not_boolean")
    if queue_has_pending is not True:
        reasons.append("queue_empty")
    if global_hold is not False:
        reasons.append("global_hold_active")
    if emergency_stop is not False:
        reasons.append("emergency_stop_active")
    if budget_verified is not True:
        reasons.append("budget_evidence_missing_or_invalid")
    if approval_verified is not True:
        reasons.append("task_approval_missing_or_invalid")
    if independent_review_pass is not True:
        reasons.append("independent_review_not_pass")
    if kill_switch is not False:
        reasons.append("kill_switch_active")
    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "continue": not reasons,
        "next_cycle_limit": 1 if not reasons else 0,
        "reasons": reasons,
    }
