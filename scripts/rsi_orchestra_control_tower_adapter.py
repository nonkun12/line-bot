"""Read-only bridge from Orchestra RSI/REA reviews into Control Tower status.

The adapter verifies the persisted review evidence and maps it to a sanitized
status row. It cannot dispatch work, approve execution, clear HOLD, merge,
deploy, or activate models.
"""
from __future__ import annotations

import re
from typing import Any

from core.rsi_executor import EvidenceLedger, canonical_digest
from core.rsi_orchestra import OrchestraRSIBatch

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def coordinate_rsi_orchestra_batch(
    batch: object,
    *,
    ledger: EvidenceLedger,
    expected_repository: str,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Return a fail-closed Control Tower status row for one reviewed batch."""
    if not isinstance(batch, OrchestraRSIBatch) or not isinstance(ledger, EvidenceLedger):
        return _blocked("invalid_batch_or_ledger")
    if (
        not isinstance(expected_repository, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_repository)
        or not isinstance(expected_head_sha, str)
        or not _SHA_RE.fullmatch(expected_head_sha)
    ):
        return _blocked("invalid_expected_identity")
    if (
        batch.dispatch_authorized is not False
        or batch.scheduler_started is not False
        or batch.execution_authorized is not False
        or batch.model_activated is not False
        or batch.proposal_batch.execution_authorized is not False
        or batch.proposal_batch.scheduler_started is not False
        or batch.proposal_batch.model_activated is not False
    ):
        return _blocked("unexpected_authority_flag")

    if ledger.verify() is not True:
        return _blocked("evidence_ledger_integrity_failed")

    allowed = {"PASS", "FAIL", "BLOCKED"}
    event_ids: list[str] = []
    for review in batch.reviews:
        handoff = review.handoff
        if (
            review.status not in allowed
            or handoff.repository != expected_repository
            or handoff.head_sha != expected_head_sha
            or not _DIGEST_RE.fullmatch(handoff.plan_digest)
            or not _DIGEST_RE.fullmatch(handoff.candidate_digest)
            or not _DIGEST_RE.fullmatch(handoff.evidence_digest)
            or not isinstance(review.evidence_event_id, str)
            or not review.evidence_event_id.startswith("orchestra-rea:")
        ):
            return _blocked("review_identity_or_evidence_invalid")
        try:
            payload, _event_digest = ledger.read_event(review.evidence_event_id)
        except Exception:
            return _blocked("review_evidence_missing_or_tampered")
        candidate = review.candidate
        evaluation = review.evaluation
        if candidate is None:
            return _blocked("review_candidate_missing")
        candidate_digest = canonical_digest({
            "candidate_id": candidate.candidate_id,
            "objective": candidate.objective,
            "proposal": candidate.proposal,
            "constraints": list(candidate.constraints),
            "evidence": dict(candidate.evidence),
        })
        if candidate_digest != handoff.candidate_digest:
            return _blocked("candidate_digest_mismatch")
        expected = {
            "task_id": handoff.task_id,
            "repository": handoff.repository,
            "head_sha": handoff.head_sha,
            "experiment_id": handoff.experiment_id,
            "plan_digest": handoff.plan_digest,
            "candidate_digest": handoff.candidate_digest,
            "evidence_digest": handoff.evidence_digest,
            "status": review.status,
            "candidate_id": candidate.candidate_id,
            "critic_decision": evaluation.passed if evaluation else None,
            "critic_score": evaluation.score if evaluation else None,
            "critic_feedback_digest": canonical_digest(evaluation.feedback) if evaluation else None,
            "execution_authorized": False,
            "patch_authorized": False,
            "merge_deploy_authorized": False,
            "hold_clear_authorized": False,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            return _blocked("review_evidence_binding_mismatch")
        if review.status == "PASS" and (
            review.evaluation is None or review.evaluation.passed is not True
        ):
            return _blocked("critic_pass_evidence_missing")
        if review.status == "FAIL" and (
            review.evaluation is None or review.evaluation.passed is not False
        ):
            return _blocked("critic_failure_evidence_missing")
        event_ids.append(review.evidence_event_id)

    if batch.status == "NO_WORK" or batch.status == "NO_REVIEWABLE_PLAN":
        status, reason, action = "NO_CHANGE", "no_reviewable_rsi_plan", "REPORT_NO_CHANGE"
    elif batch.status == "BLOCKED" or any(item.status == "BLOCKED" for item in batch.reviews):
        status, reason, action = "BLOCKED", "rsi_rea_review_blocked", "HOLD_AND_REPORT"
    elif batch.status == "REVIEW_REQUIRED" or any(item.status == "FAIL" for item in batch.reviews):
        status, reason, action = "FAIL", "rea_critic_review_required", "REPORT_REVIEW_REQUIRED"
    elif batch.status == "REVIEW_PASS_PROPOSAL_ONLY" and batch.reviews and all(
        item.status == "PASS" for item in batch.reviews
    ):
        status, reason, action = "PASS", "rea_review_pass_proposal_only", "REQUEST_HUMAN_REVIEW"
    else:
        return _blocked("batch_status_inconsistent")

    return {
        "phase": "RSI_REVIEW",
        "status": status,
        "reason_code": reason,
        "next_action": action,
        "repository": expected_repository,
        "head_sha": expected_head_sha,
        "review_count": len(batch.reviews),
        "review_evidence_event_ids": event_ids,
        "allow_continue": False,
        "proposal_only": True,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
        "scheduler_started": False,
        "model_activated": False,
    }


def _blocked(reason_code: str) -> dict[str, Any]:
    return {
        "phase": "RSI_REVIEW",
        "status": "BLOCKED",
        "reason_code": reason_code,
        "next_action": "HOLD_AND_REPORT",
        "allow_continue": False,
        "proposal_only": True,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
        "scheduler_started": False,
        "model_activated": False,
    }


__all__ = ["coordinate_rsi_orchestra_batch"]
