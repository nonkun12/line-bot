"""Deterministic five-stage RSI cycle and fail-closed continuation gate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable

from scripts.orca_rsi_review_attestation import (
    ReviewAttestationRejected,
    verify_independent_review,
)

RSI_STAGES = ("evaluate", "diagnose", "hypothesize", "experiment", "select_evolve")
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


def record_stage(cycle: Any, *, stage: str, evidence: str,
                 result: str | None = None) -> dict[str, Any]:
    """Record exactly the next RSI stage and return a copied cycle."""
    if (not isinstance(cycle, dict) or type(cycle.get("schema_version")) is not int
            or cycle["schema_version"] != 1):
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
    if stage != RSI_STAGES[len(completed)]:
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
    independent_review_attestation: Any,
    review_public_key_pem: str | bytes,
    review_nonce: str,
    used_attestation_hashes: Iterable[str],
    repository: str,
    allowed_reviewers: Iterable[str],
    now: datetime,
    expected_commit_sha: str,
    kill_switch: bool,
) -> dict[str, Any]:
    """Continue once only after this gate cryptographically verifies the review.

    The caller must atomically reserve the one-time nonce and persist the
    returned attestation hash in durable state before triggering any work.
    """
    reasons: list[str] = []
    valid_cycle = (isinstance(cycle, dict)
                   and type(cycle.get("schema_version")) is int
                   and cycle["schema_version"] == 1)
    if not valid_cycle:
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
    if kill_switch is not False:
        reasons.append("kill_switch_active")
    if not isinstance(expected_commit_sha, str) or len(expected_commit_sha) != 40:
        reasons.append("expected_commit_sha_invalid")

    if valid_cycle and isinstance(expected_commit_sha, str) and len(expected_commit_sha) == 40:
        try:
            verify_independent_review(
                independent_review_attestation,
                review_public_key_pem,
                repository=repository,
                cycle_id=cycle["cycle_id"],
                commit_sha=expected_commit_sha,
                expected_nonce=review_nonce,
                used_attestation_hashes=used_attestation_hashes,
                now=now,
                allowed_reviewers=allowed_reviewers,
            )
        except ReviewAttestationRejected as exc:
            reasons.append(f"independent_review_rejected:{exc}")
    else:
        reasons.append("independent_review_context_missing")

    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "continue": not reasons,
        "next_cycle_limit": 1 if not reasons else 0,
        "reasons": reasons,
    }
