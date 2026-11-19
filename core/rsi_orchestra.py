"""Bounded Orchestra -> RSI -> REA hand-off; proposal/review only.

This module coordinates a bounded RSI proposal batch and binds each REA
Creator/Critic review to the exact repository HEAD, experiment plan, candidate,
and independently verified evidence. It never dispatches work or authorizes
execution, merge, deployment, HOLD release, or model activation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import uuid
import re
from typing import Callable, Mapping

from .creator_critic import CriticAgent, CriticEvaluation, CreatorAgent, ImprovementCandidate
from .rsi_executor import RSIError, canonical_digest
from .rsi_supervisor import (
    Advisor,
    RSIProposalInput,
    RSISupervisorBatch,
    run_bounded_proposal_batch,
)
from .rsi_executor import RSIExecutor

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_METRICS = ("accuracy", "stability", "efficiency", "safety")


@dataclass(frozen=True)
class REAHandoff:
    """Immutable identity envelope presented to the independent Critic."""

    task_id: str
    repository: str
    head_sha: str
    experiment_id: str
    plan_digest: str
    candidate_digest: str
    evidence_digest: str


@dataclass(frozen=True)
class REAReview:
    handoff: REAHandoff
    candidate: ImprovementCandidate | None
    evaluation: CriticEvaluation | None
    status: str
    reason_code: str | None = None
    execution_authorized: bool = False
    patch_authorized: bool = False
    merge_deploy_authorized: bool = False
    hold_clear_authorized: bool = False
    evidence_event_id: str | None = None


@dataclass(frozen=True)
class OrchestraRSIBatch:
    proposal_batch: RSISupervisorBatch
    reviews: tuple[REAReview, ...]
    status: str
    dispatch_authorized: bool = False
    scheduler_started: bool = False
    execution_authorized: bool = False
    model_activated: bool = False


EvidenceProvider = Callable[[object, ImprovementCandidate], Mapping[str, object]]
EvidenceVerifier = Callable[[Mapping[str, object], Mapping[str, str]], bool]


def _validate_evidence(evidence: object) -> Mapping[str, object]:
    if not isinstance(evidence, Mapping):
        raise RSIError("REA evidence must be a mapping")
    for name in _METRICS:
        value = evidence.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RSIError("REA evidence metrics are incomplete")
        if not 0.0 <= float(value) <= 1.0:
            raise RSIError("REA evidence metric is out of range")
    evidence_ref = evidence.get("evidence_ref")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip() or len(evidence_ref) > 512:
        raise RSIError("REA evidence reference is required")
    return evidence


def _persist_review(executor: RSIExecutor, review: REAReview) -> REAReview:
    """Persist a digest-only review record; ledger failure converts it to BLOCKED."""
    try:
        ledger = executor.ledger
        if ledger.verify() is not True:
            raise RSIError("RSI evidence ledger integrity check failed")
        event_id = "orchestra-rea:" + uuid.uuid4().hex
        evaluation = review.evaluation
        payload = {
            "task_id": review.handoff.task_id,
            "repository": review.handoff.repository,
            "head_sha": review.handoff.head_sha,
            "experiment_id": review.handoff.experiment_id,
            "plan_digest": review.handoff.plan_digest,
            "candidate_digest": review.handoff.candidate_digest,
            "evidence_digest": review.handoff.evidence_digest,
            "status": review.status,
            "reason_code": review.reason_code,
            "candidate_id": review.candidate.candidate_id if review.candidate else None,
            "critic_decision": evaluation.passed if evaluation else None,
            "critic_score": evaluation.score if evaluation else None,
            "critic_feedback_digest": canonical_digest(evaluation.feedback) if evaluation else None,
            "execution_authorized": False,
            "patch_authorized": False,
            "merge_deploy_authorized": False,
            "hold_clear_authorized": False,
        }
        ledger.append(event_id, "orchestra_rea_review", payload)
        if ledger.verify() is not True:
            raise RSIError("RSI evidence ledger failed post-append verification")
        return replace(review, evidence_event_id=event_id)
    except Exception:
        return replace(
            review, status="BLOCKED", reason_code="review_evidence_persistence_failed",
            evidence_event_id=None,
        )


def run_orchestra_rsi_batch(
    executor: RSIExecutor,
    input_source: Callable[[], RSIProposalInput],
    *,
    creator: CreatorAgent,
    critic: CriticAgent,
    repository: str,
    head_sha: str,
    objective: str,
    evidence_provider: EvidenceProvider,
    verify_evidence: EvidenceVerifier,
    max_cycles: int = 4,
    advisor: Advisor | None = None,
) -> OrchestraRSIBatch:
    """Run bounded RSI proposal ticks, then SHA/digest-bound REA reviews only.

    Creator and Critic must use distinct injected callable objects. The evidence
    verifier is mandatory and must validate the supplied evidence against the
    exact hand-off bindings before the Critic sees it.
    """
    if not isinstance(executor, RSIExecutor) or not callable(input_source):
        raise RSIError("typed RSI executor and input source are required")
    if not isinstance(creator, CreatorAgent) or not isinstance(critic, CriticAgent):
        raise RSIError("separate typed REA Creator and Critic are required")
    if getattr(creator, "_model", None) is getattr(critic, "_model", None):
        raise RSIError("REA Creator and Critic must use distinct injected callables")
    if not isinstance(repository, str) or not _REPO_RE.fullmatch(repository):
        raise RSIError("repository identity is invalid")
    if not isinstance(head_sha, str) or not _SHA_RE.fullmatch(head_sha):
        raise RSIError("exact repository HEAD SHA is required")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 2000:
        raise RSIError("bounded objective is required")
    if not callable(evidence_provider) or not callable(verify_evidence):
        raise RSIError("REA evidence provider and independent verifier are required")

    batch = run_bounded_proposal_batch(
        executor, input_source, max_cycles=max_cycles, advisor=advisor
    )
    reviews: list[REAReview] = []
    for cycle in batch.cycles:
        plan = cycle.selected_plan
        if plan is None:
            continue
        hypothesis = next(
            (item for item in cycle.hypotheses if item.hypothesis_id == plan.hypothesis_id),
            None,
        )
        if hypothesis is None:
            raise RSIError("selected RSI plan has no matching hypothesis lineage")

        task_id = "rsi:" + plan.experiment_id
        if not _TASK_RE.fullmatch(task_id):
            raise RSIError("RSI experiment identity is invalid")
        creator_evidence = {
            "repository": repository,
            "head_sha": head_sha,
            "experiment_id": plan.experiment_id,
            "plan_digest": plan.plan_digest,
            "baseline_digest": plan.baseline_digest,
            "candidate_digest": plan.candidate_digest,
            "protocol_digest": plan.protocol_digest,
            "hypothesis": hypothesis.statement,
            "falsification_condition": hypothesis.falsification_condition,
        }
        candidate: ImprovementCandidate | None = None
        try:
            candidate = creator.create(objective, creator_evidence)
            candidate_digest = canonical_digest({
                "candidate_id": candidate.candidate_id,
                "objective": candidate.objective,
                "proposal": candidate.proposal,
                "constraints": list(candidate.constraints),
                "evidence": dict(candidate.evidence),
            })
            measured = _validate_evidence(evidence_provider(plan, candidate))
            evidence_digest = canonical_digest(dict(measured))
            binding = {
                "task_id": task_id,
                "repository": repository,
                "head_sha": head_sha,
                "experiment_id": plan.experiment_id,
                "plan_digest": plan.plan_digest,
                "candidate_digest": candidate_digest,
                "evidence_digest": evidence_digest,
            }
            if verify_evidence(measured, binding) is not True:
                reviews.append(_persist_review(executor, REAReview(
                    REAHandoff(**binding), candidate, None, "BLOCKED",
                    "evidence_verification_failed",
                )))
                continue
            critic_input = {**dict(measured), **binding}
            evaluation = critic.evaluate(candidate, critic_input)
            if (
                evaluation.candidate_id != candidate.candidate_id
                or any(evaluation.evidence.get(key) != value for key, value in critic_input.items())
            ):
                reviews.append(_persist_review(executor, REAReview(
                    REAHandoff(**binding), candidate, None, "BLOCKED",
                    "critic_binding_mismatch",
                )))
                continue
            reviews.append(_persist_review(executor, REAReview(
                REAHandoff(**binding), candidate, evaluation,
                "PASS" if evaluation.passed else "FAIL",
            )))
        except Exception as exc:
            # Keep diagnostics non-sensitive and never turn adapter failure into PASS.
            fallback_candidate_digest = (
                canonical_digest({"candidate_id": candidate.candidate_id,
                                  "proposal": candidate.proposal})
                if candidate is not None else "0" * 64
            )
            binding = {
                "task_id": task_id,
                "repository": repository,
                "head_sha": head_sha,
                "experiment_id": plan.experiment_id,
                "plan_digest": plan.plan_digest,
                "candidate_digest": fallback_candidate_digest,
                "evidence_digest": "0" * 64,
            }
            reviews.append(_persist_review(executor, REAReview(
                REAHandoff(**binding), candidate, None, "BLOCKED",
                "rea_adapter_" + type(exc).__name__,
            )))

    if not batch.cycles:
        status = "NO_WORK"
    elif any(item.status == "BLOCKED" for item in reviews):
        status = "BLOCKED"
    elif any(item.status == "FAIL" for item in reviews):
        status = "REVIEW_REQUIRED"
    elif reviews and all(item.status == "PASS" for item in reviews):
        status = "REVIEW_PASS_PROPOSAL_ONLY"
    else:
        status = "NO_REVIEWABLE_PLAN"
    return OrchestraRSIBatch(batch, tuple(reviews), status)


__all__ = [
    "OrchestraRSIBatch",
    "REAReview",
    "REAHandoff",
    "run_orchestra_rsi_batch",
]
