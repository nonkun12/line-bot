"""Deterministic five-stage RSI cycle and fail-closed continuation gate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Iterable

from scripts.orca_rsi_review_replay import verify_and_consume_review_once


RSI_STAGES = ("evaluate", "diagnose", "hypothesize", "experiment", "select_evolve")
FINAL_RESULTS = {"PASS", "FAIL", "NO_CHANGE", "BLOCKED"}
MAX_EVIDENCE_LENGTH = 2_000
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class RSICycleRejected(ValueError):
    """Raised when a cycle transition is incomplete or out of order."""


def new_cycle(cycle_id: str) -> dict[str, Any]:
    """Create an empty five-stage cycle; this does not persist it."""
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
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
    independent_review_attestation: Any,
    review_public_key_pem: str | bytes,
    review_nonce: str,
    approval_claim: Any,
    approval_keyring: Any,
    approval_key_signer_map: Any,
    allowed_approvers: Iterable[str],
    budget_claim: Any,
    budget_keyring: Any,
    budget_key_signer_map: Any,
    allowed_budget_issuers: Iterable[str],
    expected_budget_unit: str,
    resolved_budget_evidence: Any,
    task_id: str,
    task_digest: str,
    replay_store: Any,
    replay_snapshot: Any,
    repository: str,
    allowed_reviewers: Iterable[str],
    public_key_reviewer_id: str,
    implementer_id: str,
    now: datetime,
    expected_commit_sha: str,
    kill_switch: bool,
) -> dict[str, Any]:
    """Verify and consume review, approval, and budget evidence in sequence.

    Each successful CAS advances the snapshot used by the next claim. A later
    failure may burn earlier claims; this is intentional fail-closed behavior.
    This gate never starts a worker and never accepts caller-supplied verified
    booleans as evidence.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from scripts.orca_rsi_trust_claim_replay import (
        verify_and_consume_budget_authorization_once,
        verify_and_consume_task_approval_once,
    )

    reasons: list[str] = []

    # Trust domains must not share a signing key: separate key IDs and
    # allowlists alone do not establish independent authority.
    if isinstance(approval_claim, dict) and isinstance(budget_claim, dict):
        try:
            approval_key_id = approval_claim.get("key_id")
            budget_key_id = budget_claim.get("key_id")
            approval_pem = approval_keyring.get(approval_key_id)
            budget_pem = budget_keyring.get(budget_key_id)
            review_key = serialization.load_pem_public_key(
                review_public_key_pem.encode("utf-8")
                if isinstance(review_public_key_pem, str) else review_public_key_pem
            )
            approval_key = serialization.load_pem_public_key(
                approval_pem.encode("utf-8") if isinstance(approval_pem, str) else approval_pem
            )
            budget_key = serialization.load_pem_public_key(
                budget_pem.encode("utf-8") if isinstance(budget_pem, str) else budget_pem
            )
            if not all(isinstance(key, Ed25519PublicKey)
                       for key in (review_key, approval_key, budget_key)):
                raise ValueError("trust_key_type_invalid")
            raw_keys = [
                key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                for key in (review_key, approval_key, budget_key)
            ]
            if len(set(raw_keys)) != 3 or approval_key_id == budget_key_id:
                reasons.append("trust_signing_keys_not_independent")
        except Exception:
            reasons.append("trust_signing_keys_missing_or_invalid")
    valid_cycle = (isinstance(cycle, dict)
                   and type(cycle.get("schema_version")) is int
                   and cycle["schema_version"] == 1)
    if not valid_cycle:
        reasons.append("cycle_missing_or_invalid")
    else:
        if not isinstance(cycle.get("cycle_id"), str) or not _HEX_64.fullmatch(cycle["cycle_id"]):
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

    state = getattr(replay_snapshot, "state", None)
    if not isinstance(state, dict):
        reasons.append("replay_state_snapshot_missing")
    else:
        if type(state.get("schema_version")) is not int or state.get("schema_version") != 1:
            reasons.append("persisted_state_schema_invalid")
        revision = state.get("revision")
        if type(revision) is not int or revision < 0:
            reasons.append("persisted_state_revision_invalid")
        if state.get("global_hold") is not False:
            reasons.append("global_hold_active")
        if state.get("emergency_stop") is not False:
            reasons.append("emergency_stop_active")
        tasks = state.get("tasks")
        if not isinstance(tasks, list):
            reasons.append("persisted_queue_invalid")
        else:
            task_ids: set[str] = set()
            queued = []
            for item in tasks:
                if (not isinstance(item, dict)
                        or not isinstance(item.get("task_id"), str)
                        or not item["task_id"].strip()
                        or not isinstance(item.get("status"), str)
                        or not item["status"].strip()):
                    reasons.append("persisted_queue_entry_invalid")
                    continue
                if item["task_id"] in task_ids:
                    reasons.append("persisted_queue_duplicate_task_id")
                    continue
                task_ids.add(item["task_id"])
                if item["status"] == "queued":
                    if not isinstance(item.get("task_digest"), str) or not _HEX_64.fullmatch(item["task_digest"]):
                        reasons.append("persisted_queued_task_digest_invalid")
                    queued.append(item)
            if len(queued) != 1:
                reasons.append("queued_task_count_not_exactly_one")
            elif (queued[0].get("task_id") != task_id
                  or queued[0].get("task_digest") != task_digest):
                reasons.append("queued_task_binding_mismatch")
        if state.get("active_lease") is not None:
            reasons.append("worker_lease_already_active")

    if (isinstance(approval_claim, dict)
            and isinstance(public_key_reviewer_id, str)
            and approval_claim.get("approver_id") == public_key_reviewer_id):
        reasons.append("reviewer_must_be_independent_of_approver")
    if not isinstance(task_id, str) or not task_id.strip():
        reasons.append("task_id_invalid")
    if not isinstance(task_digest, str) or not _HEX_64.fullmatch(task_digest):
        reasons.append("task_digest_invalid")
    if not isinstance(repository, str) or repository.count("/") != 1:
        reasons.append("repository_invalid")
    if not isinstance(expected_commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_commit_sha):
        reasons.append("expected_commit_sha_invalid")
    if not isinstance(implementer_id, str) or not implementer_id.strip():
        reasons.append("implementer_identity_missing")
    if type(kill_switch) is not bool:
        reasons.append("kill_switch_not_boolean")
    if kill_switch is not False:
        reasons.append("kill_switch_active")

    consumed_review = consumed_approval = consumed_budget = None
    current_snapshot = replay_snapshot
    if not reasons:
        try:
            consumed_review = verify_and_consume_review_once(
                store=replay_store, snapshot=current_snapshot,
                attestation=independent_review_attestation,
                public_key_pem=review_public_key_pem,
                repository=repository, cycle_id=cycle["cycle_id"],
                commit_sha=expected_commit_sha, expected_nonce=review_nonce,
                allowed_reviewers=allowed_reviewers,
                public_key_reviewer_id=public_key_reviewer_id,
                implementer_id=implementer_id, now=now,
            )
            current_snapshot = consumed_review["snapshot"]
        except Exception as exc:
            reasons.append(f"independent_review_rejected:{type(exc).__name__}:{exc}")

    if not reasons:
        try:
            consumed_approval = verify_and_consume_task_approval_once(
                store=replay_store, snapshot=current_snapshot, claim=approval_claim,
                keyring=approval_keyring, key_signer_map=approval_key_signer_map,
                allowed_approvers=allowed_approvers,
                repository=repository, task_id=task_id, task_digest=task_digest,
                cycle_id=cycle["cycle_id"], commit_sha=expected_commit_sha,
                now=now, implementer_id=implementer_id,
            )
            current_snapshot = consumed_approval["snapshot"]
        except Exception as exc:
            reasons.append(f"task_approval_rejected:{type(exc).__name__}:{exc}")

    if not reasons:
        try:
            consumed_budget = verify_and_consume_budget_authorization_once(
                store=replay_store, snapshot=current_snapshot, claim=budget_claim,
                keyring=budget_keyring, key_signer_map=budget_key_signer_map,
                allowed_issuers=allowed_budget_issuers,
                repository=repository, task_id=task_id, task_digest=task_digest,
                cycle_id=cycle["cycle_id"], commit_sha=expected_commit_sha,
                now=now, expected_budget_unit=expected_budget_unit,
                resolved_evidence=resolved_budget_evidence,
            )
            current_snapshot = consumed_budget["snapshot"]
        except Exception as exc:
            reasons.append(f"budget_authorization_rejected:{type(exc).__name__}:{exc}")

    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "continue": not reasons,
        "next_cycle_limit": 1 if not reasons else 0,
        "review_replay_status": consumed_review.get("status") if consumed_review else None,
        "approval_replay_status": consumed_approval.get("status") if consumed_approval else None,
        "budget_replay_status": consumed_budget.get("status") if consumed_budget else None,
        "review_replay_snapshot": consumed_review.get("snapshot") if consumed_review else None,
        "approval_replay_snapshot": consumed_approval.get("snapshot") if consumed_approval else None,
        "budget_replay_snapshot": consumed_budget.get("snapshot") if consumed_budget else None,
        "final_snapshot": current_snapshot if not reasons else None,
        "execution_started": False,
        "reasons": reasons,
    }
