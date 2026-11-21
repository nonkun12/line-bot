"""Strict adapter from five-stage RSI evidence to Orca's six-stage gate."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from scripts.orca_rsi_five_stage import RSI_STAGES
from scripts.orca_rsi_review_attestation import (
    ReviewAttestationRejected,
    verify_independent_review,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class RSIExecutionAdapterRejected(ValueError):
    """Raised when RSI evidence cannot safely enter the Orca execution gate."""


def to_orca_improvement_candidate(
    cycle: Any,
    *,
    cycle_id: str,
    repository: str,
    commit_sha: str,
    review_attestation: Any,
    review_public_key_pem: str | bytes,
    expected_nonce: str,
    used_attestation_hashes: Iterable[str],
    allowed_reviewers: Iterable[str],
    public_key_reviewer_id: str,
    implementer_id: str,
    now: datetime,
    evaluation: Any,
) -> dict[str, Any]:
    """Map evidence only after verifying a reviewer signature with a public key."""
    if not isinstance(cycle, dict) or type(cycle.get("schema_version")) is not int or cycle["schema_version"] != 1:
        raise RSIExecutionAdapterRejected("rsi_cycle_missing_or_invalid")
    if cycle.get("completed_stages") != list(RSI_STAGES):
        raise RSIExecutionAdapterRejected("rsi_cycle_incomplete")
    if cycle.get("result") != "PASS":
        raise RSIExecutionAdapterRejected("rsi_cycle_result_not_pass")
    evidence = cycle.get("evidence")
    if (not isinstance(evidence, dict) or set(evidence) != set(RSI_STAGES)
            or any(not isinstance(evidence.get(stage), str) or not evidence[stage].strip()
                   for stage in RSI_STAGES)):
        raise RSIExecutionAdapterRejected("rsi_cycle_evidence_invalid")
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
        raise RSIExecutionAdapterRejected("orca_cycle_id_invalid")
    if cycle.get("cycle_id") != cycle_id:
        raise RSIExecutionAdapterRejected("rsi_cycle_id_mismatch")
    if not isinstance(evaluation, dict):
        raise RSIExecutionAdapterRejected("independent_evaluation_missing")
    try:
        review = verify_independent_review(
            review_attestation,
            review_public_key_pem,
            repository=repository,
            cycle_id=cycle_id,
            commit_sha=commit_sha,
            expected_nonce=expected_nonce,
            used_attestation_hashes=used_attestation_hashes,
            now=now,
            allowed_reviewers=allowed_reviewers,
            public_key_reviewer_id=public_key_reviewer_id,
            implementer_id=implementer_id,
        )
    except ReviewAttestationRejected as exc:
        raise RSIExecutionAdapterRejected(f"independent_review_rejected:{exc}") from None

    return {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "stage": "evaluated",
        "decision": "accepted_candidate",
        "execution_authorized": False,
        "auto_apply": False,
        "auto_merge": False,
        "auto_deploy": False,
        "review_attestation_hash": review.attestation_hash,
        "review_nonce": review.nonce,
        "evidence": {
            "observed": [evidence["evaluate"]],
            "diagnosed": [evidence["diagnose"]],
            "proposed": [evidence["hypothesize"]],
            "tested": [evidence["experiment"]],
            "reviewed": list(review.evidence_refs),
            "evaluated": [evidence["select_evolve"]],
        },
        "details": {"evaluation": dict(evaluation)},
    }
