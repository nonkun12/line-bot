"""Stages 186-190: signed longitudinal evidence and multi-generation lineage.

All outputs are deterministic, bounded, independently verifiable proposals. No model
execution, tensor/weight mutation, parameter merge, generation advancement, or activation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from itertools import islice
from typing import Callable, Iterable

from .ai_factory_stage181_185_intergeneration_evolution import (
    EvolutionReadinessCertificate,
    stage185_readiness_verifier,
)


class LongitudinalEvolutionError(ValueError):
    """Raised when multi-generation evidence is incomplete, unsafe, or inconsistent."""


_HEX = re.compile(r"^[0-9a-f]{64}$")
_MAX_GENERATION = 10**9


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LongitudinalEvolutionError("evidence is not canonically serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def _unsigned_digest(value: object) -> str:
    try:
        payload = asdict(value)
    except (TypeError, ValueError) as exc:
        raise LongitudinalEvolutionError("signed evidence has an invalid record shape") from exc
    if "signature" not in payload:
        raise LongitudinalEvolutionError("signed evidence has no signature field")
    payload.pop("signature")
    return _digest(payload)


def _digest_ok(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise LongitudinalEvolutionError(f"{label} must be a lowercase SHA-256 digest")


def _id_ok(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise LongitudinalEvolutionError(f"{label} is invalid")


def _number_ok(value: object, label: str, *, minimum: float | None = None,
               maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LongitudinalEvolutionError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise LongitudinalEvolutionError(f"{label} is below its minimum")
    if maximum is not None and value > maximum:
        raise LongitudinalEvolutionError(f"{label} is above its maximum")


def _bounded_rows(values: Iterable[object], limit: int, label: str) -> tuple:
    """Consume at most limit+1 values; never materialize an unbounded iterable."""
    if type(limit) is not int or limit < 1:
        raise LongitudinalEvolutionError(f"{label} limit is invalid")
    try:
        rows = tuple(islice(iter(values), limit + 1))
    except Exception as exc:
        raise LongitudinalEvolutionError(f"{label} iteration failed") from exc
    if len(rows) > limit:
        raise LongitudinalEvolutionError(f"{label} exceeds its {limit}-item bound")
    return rows


def _signed(digest: str, signature: str, verifier: Callable[[str, str], bool], label: str) -> None:
    _digest_ok(digest, label + " digest")
    if not callable(verifier):
        raise LongitudinalEvolutionError(f"{label} verifier is unavailable")
    if not isinstance(signature, str) or not signature.strip():
        raise LongitudinalEvolutionError(f"{label} signature is missing")
    try:
        valid = verifier(digest, signature)
    except Exception as exc:
        raise LongitudinalEvolutionError(f"{label} signature verification failed") from exc
    if valid is not True:
        raise LongitudinalEvolutionError(f"{label} signature verification failed")


def stage185_checkpoint_verifier(
    certificate: EvolutionReadinessCertificate, *,
    verify_signature: Callable[[str, str], bool],
) -> Callable[[str, int, str], bool]:
    """Connect a signed Stage 185 readiness certificate to Stage 186 lineage checks."""
    return stage185_readiness_verifier(certificate, verify_signature=verify_signature)


def _trusted_checkpoint(digest: str, generation: int,
                        verifier: Callable[[str, int], bool], label: str) -> None:
    _digest_ok(digest, label + " digest")
    if type(generation) is not int or not 0 <= generation < _MAX_GENERATION:
        raise LongitudinalEvolutionError(f"{label} generation is invalid")
    if not callable(verifier):
        raise LongitudinalEvolutionError(f"{label} verifier is unavailable")
    try:
        valid = verifier(digest, generation)
    except Exception as exc:
        raise LongitudinalEvolutionError(f"{label} verification failed") from exc
    if valid is not True:
        raise LongitudinalEvolutionError(f"{label} is not a trusted current checkpoint")


@dataclass(frozen=True)
class GenerationSnapshot:
    generation: int
    candidate_id: str
    artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    trial_id: str
    quality: float
    safety: float
    latency_ms: float
    memory_mb: float
    executor_id: str
    parent_digest: str
    signature: str


@dataclass(frozen=True)
class LongitudinalTrendReport:
    first_generation: int
    last_generation: int
    candidate_id: str
    evaluation_suite_digest: str
    parent_readiness_digest: str
    parent_generation: int
    policy_digest: str
    executor_id: str
    snapshot_digests: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    quality_delta: float
    safety_delta: float
    latency_delta: float
    memory_delta: float
    regressions: tuple[str, ...]
    report_digest: str
    signature: str
    proposal_only: bool = True


class Stage186LongitudinalTrendAnalyzer:
    """Measure signed, contiguous generations linked to a trusted Stage 185 checkpoint."""

    def build(
        self,
        snapshots: Iterable[GenerationSnapshot],
        *,
        parent_readiness_digest: str,
        parent_generation: int,
        verify_parent_readiness: Callable[[str, int, str], bool],
        verify_snapshot: Callable[[str, str], bool],
        verify_report_signature: Callable[[str, str], bool],
        sign_report: Callable[[str], str],
        minimum_generations: int = 3,
        minimum_safety: float = 0.95,
        max_quality_drop: float = 0.02,
        max_safety_drop: float = 0.0,
        max_latency_growth: float = 0.20,
        max_memory_growth: float = 0.20,
        hold_active: bool = False,
    ) -> LongitudinalTrendReport:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 186")
        if type(minimum_generations) is not int or not 3 <= minimum_generations <= 32:
            raise LongitudinalEvolutionError("generation window must be between 3 and 32")
        _digest_ok(parent_readiness_digest, "Stage 185 readiness")
        if type(parent_generation) is not int or not 0 <= parent_generation < _MAX_GENERATION:
            raise LongitudinalEvolutionError("parent readiness generation is invalid")
        if not callable(verify_parent_readiness):
            raise LongitudinalEvolutionError("Stage 185 readiness verifier is unavailable")
        for value, label, maximum in (
            (minimum_safety, "minimum safety", 1.0),
            (max_quality_drop, "maximum quality drop", None),
            (max_safety_drop, "maximum safety drop", None),
            (max_latency_growth, "maximum latency growth", None),
            (max_memory_growth, "maximum memory growth", None),
        ):
            _number_ok(value, label, minimum=0.0, maximum=maximum)
        if (
            minimum_safety < 0.95
            or max_quality_drop > 0.02
            or max_safety_drop > 0.0
            or max_latency_growth > 0.20
            or max_memory_growth > 0.20
        ):
            raise LongitudinalEvolutionError("Stage 186 thresholds cannot weaken the frozen evaluation policy")

        rows = _bounded_rows(snapshots, 32, "generation snapshots")
        if len(rows) < minimum_generations:
            raise LongitudinalEvolutionError("insufficient generation snapshots")
        if any(not isinstance(row, GenerationSnapshot) for row in rows):
            raise LongitudinalEvolutionError("generation snapshot record is invalid")
        generations = [row.generation for row in rows]
        if any(type(value) is not int or not 0 <= value < _MAX_GENERATION for value in generations):
            raise LongitudinalEvolutionError("generation number is invalid")
        if generations != list(range(parent_generation, parent_generation + len(rows))):
            raise LongitudinalEvolutionError("generation history is not contiguous from Stage 185")
        if len({row.candidate_id for row in rows}) != 1:
            raise LongitudinalEvolutionError("candidate lineage drift")
        if len({row.evaluation_suite_digest for row in rows}) != 1:
            raise LongitudinalEvolutionError("evaluation suite drift across generations")
        evaluators = tuple(row.evaluator_id for row in rows)
        executors = {row.executor_id for row in rows}
        trials = tuple(row.trial_id for row in rows)
        # Check actor separation before replay uniqueness so a shared executor/evaluator
        # is classified as an independence violation even when it also repeats an ID.
        if len(executors) != 1 or next(iter(executors)) in set(evaluators):
            raise LongitudinalEvolutionError("executor and evaluator must be independent")
        if len(set(evaluators)) != len(evaluators) or len(set(trials)) != len(trials):
            raise LongitudinalEvolutionError("replayed evaluator or trial identity")
        candidate_id = rows[0].candidate_id
        _id_ok(candidate_id, "candidate id")
        try:
            parent_valid = verify_parent_readiness(parent_readiness_digest, parent_generation, candidate_id)
        except Exception as exc:
            raise LongitudinalEvolutionError("Stage 185 readiness verification failed") from exc
        if parent_valid is not True:
            raise LongitudinalEvolutionError("Stage 185 readiness does not authorize this lineage")

        snapshot_digests = []
        expected_parent = parent_readiness_digest
        for row in rows:
            _id_ok(row.candidate_id, "candidate id")
            _id_ok(row.evaluator_id, "evaluator id")
            _id_ok(row.trial_id, "trial id")
            _id_ok(row.executor_id, "executor id")
            _digest_ok(row.artifact_digest, "artifact")
            _digest_ok(row.evaluation_suite_digest, "evaluation suite")
            _digest_ok(row.parent_digest, "snapshot parent")
            if row.parent_digest != expected_parent:
                raise LongitudinalEvolutionError("snapshot parent lineage mismatch")
            _number_ok(row.quality, "quality", minimum=0.0, maximum=1.0)
            _number_ok(row.safety, "safety", minimum=0.0, maximum=1.0)
            _number_ok(row.latency_ms, "latency", minimum=0.0)
            _number_ok(row.memory_mb, "memory", minimum=0.0)
            digest = _unsigned_digest(row)
            _signed(digest, row.signature, verify_snapshot, "generation snapshot")
            snapshot_digests.append(digest)
            expected_parent = digest

        first, last = rows[0], rows[-1]
        quality_delta = last.quality - first.quality
        safety_delta = last.safety - first.safety
        latency_delta = last.latency_ms - first.latency_ms
        memory_delta = last.memory_mb - first.memory_mb
        regressions = []
        if min(row.safety for row in rows) < minimum_safety:
            regressions.append("safety_floor")
        if quality_delta < -max_quality_drop:
            regressions.append("quality_decline")
        if safety_delta < -max_safety_drop:
            regressions.append("safety_decline")
        if first.latency_ms > 0 and last.latency_ms > first.latency_ms * (1 + max_latency_growth):
            regressions.append("latency_growth")
        if first.memory_mb > 0 and last.memory_mb > first.memory_mb * (1 + max_memory_growth):
            regressions.append("memory_growth")

        policy_digest = _digest({
            "minimum_generations": minimum_generations,
            "minimum_safety": minimum_safety,
            "max_quality_drop": max_quality_drop,
            "max_safety_drop": max_safety_drop,
            "max_latency_growth": max_latency_growth,
            "max_memory_growth": max_memory_growth,
            "snapshot_limit": 32,
        })
        payload = {
            "first": first.generation,
            "last": last.generation,
            "policy": policy_digest,
            "candidate": candidate_id,
            "suite": first.evaluation_suite_digest,
            "parent_readiness": parent_readiness_digest,
            "parent_generation": parent_generation,
            "executor": first.executor_id,
            "snapshots": tuple(snapshot_digests),
            "evaluators": evaluators,
            "quality_delta": quality_delta,
            "safety_delta": safety_delta,
            "latency_delta": latency_delta,
            "memory_delta": memory_delta,
            "regressions": tuple(regressions),
            "proposal_only": True,
        }
        report_digest = _digest(payload)
        signature = sign_report(report_digest)
        _signed(report_digest, signature, verify_report_signature, "Stage 186 report")
        return LongitudinalTrendReport(
            first.generation, last.generation, candidate_id, first.evaluation_suite_digest,
            parent_readiness_digest, parent_generation, policy_digest, first.executor_id, tuple(snapshot_digests),
            evaluators, quality_delta, safety_delta, latency_delta, memory_delta,
            tuple(regressions), report_digest, signature,
        )


@dataclass(frozen=True)
class GeneralizationAuditEvidence:
    trend_report_digest: str
    training_dataset_digest: str
    holdout_dataset_digest: str
    adversarial_suite_digest: str
    training_holdout_disjoint: bool
    holdout_never_used_for_training: bool
    contamination_check_passed: bool
    coverage: float
    evaluator_id: str
    signature: str


@dataclass(frozen=True)
class GeneralizationAuditReport:
    trend_report_digest: str
    audit_evidence_digest: str
    passed: bool
    coverage: float
    evaluator_id: str
    policy_digest: str
    audit_digest: str
    signature: str
    proposal_only: bool = True


def _verify_trend(trend: LongitudinalTrendReport) -> None:
    if not isinstance(trend, LongitudinalTrendReport) or not trend.proposal_only:
        raise LongitudinalEvolutionError("invalid longitudinal trend report")
    _digest_ok(trend.evaluation_suite_digest, "trend suite")
    _digest_ok(trend.parent_readiness_digest, "Stage 185 readiness")
    _digest_ok(trend.report_digest, "trend report")
    _digest_ok(trend.policy_digest, "trend policy")
    _id_ok(trend.candidate_id, "trend candidate")
    _id_ok(trend.executor_id, "trend executor")
    if (type(trend.first_generation) is not int or type(trend.last_generation) is not int
            or type(trend.parent_generation) is not int
            or trend.first_generation != trend.parent_generation
            or trend.last_generation < trend.first_generation + 2
            or trend.last_generation >= _MAX_GENERATION):
        raise LongitudinalEvolutionError("trend generation lineage is invalid")
    expected_count = trend.last_generation - trend.first_generation + 1
    if expected_count > 32:
        raise LongitudinalEvolutionError("trend evidence exceeds its 32-item bound")
    if (not isinstance(trend.snapshot_digests, tuple)
            or not isinstance(trend.evaluator_ids, tuple)
            or not isinstance(trend.regressions, tuple)):
        raise LongitudinalEvolutionError("trend evidence collections must be immutable tuples")
    if any(not isinstance(value, str) for value in trend.evaluator_ids + trend.regressions):
        raise LongitudinalEvolutionError("trend identity and regression values must be strings")
    if (len(trend.snapshot_digests) != expected_count or len(trend.evaluator_ids) != expected_count
            or len(set(trend.evaluator_ids)) != expected_count
            or trend.executor_id in set(trend.evaluator_ids)):
        raise LongitudinalEvolutionError("trend evidence identities are invalid")
    allowed_regressions = ("safety_floor", "quality_decline", "safety_decline", "latency_growth", "memory_growth")
    if len(trend.regressions) > 5 or tuple(value for value in allowed_regressions if value in set(trend.regressions)) != trend.regressions:
        raise LongitudinalEvolutionError("trend regression flags are invalid")
    for value in trend.snapshot_digests:
        _digest_ok(value, "snapshot")
    for value in trend.evaluator_ids:
        _id_ok(value, "trend evaluator")
    for value, label in ((trend.quality_delta, "quality delta"),
                         (trend.safety_delta, "safety delta"),
                         (trend.latency_delta, "latency delta"),
                         (trend.memory_delta, "memory delta")):
        _number_ok(value, label)
    payload = {
        "first": trend.first_generation,
        "last": trend.last_generation,
        "candidate": trend.candidate_id,
        "suite": trend.evaluation_suite_digest,
        "parent_readiness": trend.parent_readiness_digest,
        "parent_generation": trend.parent_generation,
        "policy": trend.policy_digest,
        "executor": trend.executor_id,
        "snapshots": trend.snapshot_digests,
        "evaluators": trend.evaluator_ids,
        "quality_delta": trend.quality_delta,
        "safety_delta": trend.safety_delta,
        "latency_delta": trend.latency_delta,
        "memory_delta": trend.memory_delta,
        "regressions": trend.regressions,
        "proposal_only": trend.proposal_only,
    }
    if _digest(payload) != trend.report_digest:
        raise LongitudinalEvolutionError("trend report digest mismatch")


class Stage187GeneralizationAuditor:
    """Require signed, disjoint, uncontaminated holdout evidence from another evaluator."""

    def build(
        self,
        trend: LongitudinalTrendReport,
        evidence: GeneralizationAuditEvidence,
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_evidence_signature: Callable[[str, str], bool],
        verify_report_signature: Callable[[str, str], bool],
        sign_report: Callable[[str], str],
        minimum_coverage: float = 0.95,
        hold_active: bool = False,
    ) -> GeneralizationAuditReport:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 187")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        if evidence.trend_report_digest != trend.report_digest:
            raise LongitudinalEvolutionError("generalization evidence lineage mismatch")
        for value, label in (
            (evidence.training_dataset_digest, "training dataset"),
            (evidence.holdout_dataset_digest, "holdout dataset"),
            (evidence.adversarial_suite_digest, "adversarial suite"),
        ):
            _digest_ok(value, label)
        if evidence.training_dataset_digest == evidence.holdout_dataset_digest:
            raise LongitudinalEvolutionError("training and holdout datasets must be distinct")
        if any(type(value) is not bool for value in (
            evidence.training_holdout_disjoint,
            evidence.holdout_never_used_for_training,
            evidence.contamination_check_passed,
        )):
            raise LongitudinalEvolutionError("holdout attestations must be explicit booleans")
        _id_ok(evidence.evaluator_id, "generalization evaluator")
        if evidence.evaluator_id in set(trend.evaluator_ids) | {trend.executor_id}:
            raise LongitudinalEvolutionError("holdout evaluator is not independent")
        _number_ok(minimum_coverage, "minimum coverage", minimum=0.0, maximum=1.0)
        if minimum_coverage < 0.95:
            raise LongitudinalEvolutionError("Stage 187 coverage threshold cannot weaken the frozen policy")
        _number_ok(evidence.coverage, "holdout coverage", minimum=0.0, maximum=1.0)
        evidence_digest = _unsigned_digest(evidence)
        _signed(evidence_digest, evidence.signature, verify_evidence_signature, "Stage 187 evidence")
        passed = (
            evidence.training_holdout_disjoint
            and evidence.holdout_never_used_for_training
            and evidence.contamination_check_passed
            and evidence.coverage >= minimum_coverage
        )
        policy_digest = _digest({"minimum_coverage": minimum_coverage, "minimum_coverage_floor": 0.95})
        payload = {
            "trend": trend.report_digest,
            "evidence": evidence_digest,
            "policy": policy_digest,
            "passed": passed,
            "coverage": evidence.coverage,
            "evaluator": evidence.evaluator_id,
            "proposal_only": True,
        }
        digest = _digest(payload)
        signature = sign_report(digest)
        _signed(digest, signature, verify_report_signature, "Stage 187 report")
        return GeneralizationAuditReport(
            trend.report_digest, evidence_digest, passed, evidence.coverage,
            evidence.evaluator_id, policy_digest, digest, signature,
        )


@dataclass(frozen=True)
class RegressionClaim:
    category: str
    affected_generation: int
    candidate_id: str
    causal_evidence_digest: str
    evaluator_id: str
    signature: str


@dataclass(frozen=True)
class RegressionAttributionReport:
    trend_report_digest: str
    generalization_audit_digest: str
    claim_digests: tuple[str, ...]
    supported_categories: tuple[str, ...]
    diagnostician_ids: tuple[str, ...]
    unsupported_claim_count: int
    report_digest: str
    signature: str
    proposal_only: bool = True


def _verify_audit(audit: GeneralizationAuditReport) -> None:
    if not isinstance(audit, GeneralizationAuditReport) or not audit.proposal_only:
        raise LongitudinalEvolutionError("invalid generalization audit report")
    _digest_ok(audit.trend_report_digest, "audit trend")
    _digest_ok(audit.audit_evidence_digest, "audit evidence")
    _digest_ok(audit.audit_digest, "audit report")
    _digest_ok(audit.policy_digest, "audit policy")
    _id_ok(audit.evaluator_id, "audit evaluator")
    if type(audit.passed) is not bool:
        raise LongitudinalEvolutionError("audit result must be an explicit boolean")
    _number_ok(audit.coverage, "audit coverage", minimum=0.0, maximum=1.0)
    payload = {
        "trend": audit.trend_report_digest,
        "evidence": audit.audit_evidence_digest,
        "passed": audit.passed,
        "coverage": audit.coverage,
        "evaluator": audit.evaluator_id,
        "policy": audit.policy_digest,
        "proposal_only": audit.proposal_only,
    }
    if _digest(payload) != audit.audit_digest:
        raise LongitudinalEvolutionError("generalization audit digest mismatch")


class Stage188RegressionAttributor:
    """Accept only signed, lineage-bound diagnostic claims; unknown causes stay unknown."""

    ALLOWED = frozenset({
        "data_drift", "evaluation_drift", "resource_pressure",
        "candidate_regression", "toolchain_change", "unknown",
    })

    def build(
        self,
        trend: LongitudinalTrendReport,
        audit: GeneralizationAuditReport,
        claims: Iterable[RegressionClaim],
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_audit_signature: Callable[[str, str], bool],
        verify_claim_signature: Callable[[str, str], bool],
        verify_report_signature: Callable[[str, str], bool],
        sign_report: Callable[[str], str],
        hold_active: bool = False,
    ) -> RegressionAttributionReport:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 188")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        _verify_audit(audit)
        _signed(audit.audit_digest, audit.signature, verify_audit_signature, "Stage 187")
        if audit.trend_report_digest != trend.report_digest:
            raise LongitudinalEvolutionError("generalization audit lineage mismatch")
        rows = _bounded_rows(claims, 64, "regression claims")
        accepted = []
        all_claim_digests = []
        seen_claim_digests = set()
        unsupported = 0
        independent_ids = set(trend.evaluator_ids) | {trend.executor_id, audit.evaluator_id}
        diagnosticians = set()
        for claim in rows:
            if not isinstance(claim, RegressionClaim):
                raise LongitudinalEvolutionError("regression claim record is invalid")
            _id_ok(claim.candidate_id, "claim candidate")
            _id_ok(claim.evaluator_id, "claim evaluator")
            _digest_ok(claim.causal_evidence_digest, "causal evidence")
            if type(claim.affected_generation) is not int:
                raise LongitudinalEvolutionError("claim generation is invalid")
            if not isinstance(claim.category, str):
                raise LongitudinalEvolutionError("claim category is invalid")
            if claim.evaluator_id in independent_ids:
                raise LongitudinalEvolutionError("diagnostician is not independent")
            diagnosticians.add(claim.evaluator_id)
            claim_digest = _unsigned_digest(claim)
            _signed(claim_digest, claim.signature, verify_claim_signature, "Stage 188 claim")
            # Replay detection and report binding apply to every signed claim, including
            # unsupported claims. Otherwise a duplicate unsupported claim could evade
            # replay detection and its evidence could be swapped without changing the
            # signed attribution report digest.
            if claim_digest in seen_claim_digests:
                raise LongitudinalEvolutionError("replayed regression claim")
            seen_claim_digests.add(claim_digest)
            all_claim_digests.append(claim_digest)
            if (claim.category not in self.ALLOWED or claim.candidate_id != trend.candidate_id
                    or not trend.first_generation <= claim.affected_generation <= trend.last_generation):
                unsupported += 1
                continue
            accepted.append((claim_digest, claim))
            if claim.category == "unknown":
                unsupported += 1
        digests = tuple(sorted(all_claim_digests))
        categories = tuple(sorted({item[1].category for item in accepted}))
        evaluator_ids = tuple(sorted(diagnosticians))
        payload = {
            "trend": trend.report_digest,
            "audit": audit.audit_digest,
            "claims": digests,
            "categories": categories,
            "diagnosticians": evaluator_ids,
            "unsupported": unsupported,
            "proposal_only": True,
        }
        digest = _digest(payload)
        signature = sign_report(digest)
        _signed(digest, signature, verify_report_signature, "Stage 188 report")
        return RegressionAttributionReport(
            trend.report_digest, audit.audit_digest, digests, categories,
            evaluator_ids, unsupported, digest, signature,
        )


@dataclass(frozen=True)
class SurvivalLedgerEntry:
    generation: int
    candidate_id: str
    artifact_digest: str
    strategy_id: str
    outcome: str
    evidence_digest: str
    signature: str


@dataclass(frozen=True)
class MultiGenerationSurvivalLedger:
    previous_ledger_digest: str
    previous_generation: int
    entries: tuple[SurvivalLedgerEntry, ...]
    ledger_digest: str
    signature: str
    proposal_only: bool = True


class Stage189SurvivalLedger:
    """Build a bounded, signed, contiguous append proposal from a trusted checkpoint."""

    OUTCOMES = frozenset({"survived", "retired_proposal", "reexplore_proposal"})

    def build(
        self,
        *,
        previous_ledger_digest: str,
        previous_generation: int,
        entries: Iterable[SurvivalLedgerEntry],
        verify_previous_ledger: Callable[[str, int], bool],
        verify_entry_signature: Callable[[str, str], bool],
        verify_report_signature: Callable[[str, str], bool],
        sign_report: Callable[[str], str],
        max_entries: int = 128,
        hold_active: bool = False,
    ) -> MultiGenerationSurvivalLedger:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 189")
        _trusted_checkpoint(previous_ledger_digest, previous_generation, verify_previous_ledger,
                            "survival ledger predecessor")
        if type(max_entries) is not int or not 1 <= max_entries <= 512:
            raise LongitudinalEvolutionError("ledger entry bound is invalid")
        rows = _bounded_rows(entries, max_entries, "survival ledger entries")
        if not rows:
            raise LongitudinalEvolutionError("survival ledger must not be empty")
        if any(not isinstance(row, SurvivalLedgerEntry) for row in rows):
            raise LongitudinalEvolutionError("survival ledger entry record is invalid")
        keys = set()
        generations = set()
        for row in rows:
            if type(row.generation) is not int or not previous_generation < row.generation <= previous_generation + 32:
                raise LongitudinalEvolutionError("ledger generation is not a bounded append")
            _id_ok(row.candidate_id, "ledger candidate")
            _id_ok(row.strategy_id, "ledger strategy")
            _digest_ok(row.artifact_digest, "ledger artifact")
            _digest_ok(row.evidence_digest, "ledger evidence")
            if row.outcome not in self.OUTCOMES:
                raise LongitudinalEvolutionError("ledger outcome is invalid")
            entry_digest = _unsigned_digest(row)
            _signed(entry_digest, row.signature, verify_entry_signature, "survival ledger entry")
            key = (row.generation, row.candidate_id, row.strategy_id)
            if key in keys:
                raise LongitudinalEvolutionError("duplicate ledger entry")
            keys.add(key)
            generations.add(row.generation)
        last_generation = max(generations)
        if generations != set(range(previous_generation + 1, last_generation + 1)):
            raise LongitudinalEvolutionError("ledger generations contain a gap")
        ordered = tuple(sorted(rows, key=lambda x: (x.generation, x.candidate_id, x.strategy_id)))
        digest = _digest({
            "previous": previous_ledger_digest,
            "previous_generation": previous_generation,
            "entries": [asdict(item) for item in ordered],
            "proposal_only": True,
        })
        signature = sign_report(digest)
        _signed(digest, signature, verify_report_signature, "Stage 189 ledger")
        return MultiGenerationSurvivalLedger(
            previous_ledger_digest, previous_generation, ordered, digest, signature
        )


@dataclass(frozen=True)
class MultiGenerationEvolutionCertificate:
    first_generation: int
    last_generation: int
    parent_readiness_digest: str
    trend_report_digest: str
    generalization_audit_digest: str
    regression_attribution_digest: str
    survival_ledger_digest: str
    certificate_digest: str
    certificate_signature: str
    ready_for_human_review: bool
    proposal_only: bool = True
    weight_mutation_authorized: bool = False
    generation_advance_authorized: bool = False
    model_activation_authorized: bool = False
    production_switch_authorized: bool = False


class Stage190LongitudinalCertificatePackager:
    """Verify every upstream signature, checkpoint, digest and lineage before review."""

    def build(
        self,
        trend: LongitudinalTrendReport,
        audit: GeneralizationAuditReport,
        attribution: RegressionAttributionReport,
        ledger: MultiGenerationSurvivalLedger,
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_parent_readiness: Callable[[str, int, str], bool],
        verify_audit_signature: Callable[[str, str], bool],
        verify_attribution_signature: Callable[[str, str], bool],
        verify_ledger_signature: Callable[[str, str], bool],
        verify_ledger_entry_signature: Callable[[str, str], bool],
        verify_ledger_predecessor: Callable[[str, int], bool],
        sign_certificate: Callable[[str], str],
        verify_certificate_signature: Callable[[str, str], bool],
        hold_active: bool = False,
    ) -> MultiGenerationEvolutionCertificate:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 190")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        if not callable(verify_parent_readiness):
            raise LongitudinalEvolutionError("Stage 185 readiness verifier is unavailable")
        try:
            parent_valid = verify_parent_readiness(
                trend.parent_readiness_digest, trend.parent_generation, trend.candidate_id
            )
        except Exception as exc:
            raise LongitudinalEvolutionError("Stage 185 readiness revalidation failed") from exc
        if parent_valid is not True:
            raise LongitudinalEvolutionError("Stage 185 readiness is not a trusted current checkpoint")
        _verify_audit(audit)
        _signed(audit.audit_digest, audit.signature, verify_audit_signature, "Stage 187")
        if audit.trend_report_digest != trend.report_digest or audit.passed is not True:
            raise LongitudinalEvolutionError("generalization audit failed or lineage mismatch")

        if not isinstance(attribution, RegressionAttributionReport) or not attribution.proposal_only:
            raise LongitudinalEvolutionError("regression attribution report is invalid")
        if (not isinstance(attribution.claim_digests, tuple)
                or not isinstance(attribution.supported_categories, tuple)
                or not isinstance(attribution.diagnostician_ids, tuple)):
            raise LongitudinalEvolutionError("attribution evidence collections must be immutable tuples")
        if (len(attribution.claim_digests) > 64 or len(attribution.diagnostician_ids) > 64
                or len(attribution.supported_categories) > len(Stage188RegressionAttributor.ALLOWED)):
            raise LongitudinalEvolutionError("attribution evidence exceeds its bounded collection limits")
        if any(not isinstance(value, str) for value in (
            *attribution.claim_digests, *attribution.supported_categories, *attribution.diagnostician_ids
        )):
            raise LongitudinalEvolutionError("attribution evidence values must be strings")
        _digest_ok(attribution.trend_report_digest, "attribution trend")
        _digest_ok(attribution.generalization_audit_digest, "attribution audit")
        _digest_ok(attribution.report_digest, "attribution report")
        if (attribution.trend_report_digest != trend.report_digest
                or attribution.generalization_audit_digest != audit.audit_digest):
            raise LongitudinalEvolutionError("regression attribution lineage mismatch")
        if (type(attribution.unsupported_claim_count) is not int
                or not 0 <= attribution.unsupported_claim_count <= len(attribution.claim_digests) <= 64):
            raise LongitudinalEvolutionError("unsupported claim count is outside bounds")
        if (len(attribution.claim_digests) > 64
                or attribution.claim_digests != tuple(sorted(set(attribution.claim_digests)))):
            raise LongitudinalEvolutionError("regression claim digest set is invalid")
        for value in attribution.claim_digests:
            _digest_ok(value, "regression claim")
        if (attribution.supported_categories != tuple(sorted(set(attribution.supported_categories)))
                or any(value not in Stage188RegressionAttributor.ALLOWED
                       for value in attribution.supported_categories)):
            raise LongitudinalEvolutionError("regression attribution categories are invalid")
        if attribution.diagnostician_ids != tuple(sorted(set(attribution.diagnostician_ids))):
            raise LongitudinalEvolutionError("diagnostician identities are invalid")
        for value in attribution.diagnostician_ids:
            _id_ok(value, "diagnostician")
            if value in set(trend.evaluator_ids) | {trend.executor_id, audit.evaluator_id}:
                raise LongitudinalEvolutionError("diagnostician lineage is not independent")
        _signed(attribution.report_digest, attribution.signature,
                verify_attribution_signature, "Stage 188")
        expected_attribution = _digest({
            "trend": attribution.trend_report_digest,
            "audit": attribution.generalization_audit_digest,
            "claims": attribution.claim_digests,
            "categories": attribution.supported_categories,
            "diagnosticians": attribution.diagnostician_ids,
            "unsupported": attribution.unsupported_claim_count,
            "proposal_only": attribution.proposal_only,
        })
        if expected_attribution != attribution.report_digest:
            raise LongitudinalEvolutionError("regression attribution digest mismatch")

        if not isinstance(ledger, MultiGenerationSurvivalLedger) or not ledger.proposal_only:
            raise LongitudinalEvolutionError("survival ledger is not proposal-only")
        _digest_ok(ledger.previous_ledger_digest, "previous ledger")
        _digest_ok(ledger.ledger_digest, "survival ledger")
        if (type(ledger.previous_generation) is not int
                or ledger.previous_generation != trend.first_generation
                or not isinstance(ledger.entries, tuple)
                or not ledger.entries or len(ledger.entries) > 512):
            raise LongitudinalEvolutionError("survival ledger bounds or starting generation invalid")
        _trusted_checkpoint(ledger.previous_ledger_digest, ledger.previous_generation,
                            verify_ledger_predecessor, "survival ledger predecessor")
        _signed(ledger.ledger_digest, ledger.signature, verify_ledger_signature, "Stage 189")
        keys = set()
        generations = set()
        for entry in ledger.entries:
            if not isinstance(entry, SurvivalLedgerEntry):
                raise LongitudinalEvolutionError("survival ledger entry record is invalid")
            _id_ok(entry.candidate_id, "ledger candidate")
            _id_ok(entry.strategy_id, "ledger strategy")
            _digest_ok(entry.artifact_digest, "ledger artifact")
            _digest_ok(entry.evidence_digest, "ledger evidence")
            if entry.candidate_id != trend.candidate_id:
                raise LongitudinalEvolutionError("survival ledger candidate lineage mismatch")
            if type(entry.generation) is not int or not trend.first_generation < entry.generation <= trend.last_generation:
                raise LongitudinalEvolutionError("survival ledger generation outside trend window")
            if entry.outcome not in Stage189SurvivalLedger.OUTCOMES:
                raise LongitudinalEvolutionError("survival ledger outcome invalid")
            _signed(_unsigned_digest(entry), entry.signature,
                    verify_ledger_entry_signature, "survival ledger entry")
            key = (entry.generation, entry.candidate_id, entry.strategy_id)
            if key in keys:
                raise LongitudinalEvolutionError("duplicate survival ledger entry")
            keys.add(key)
            generations.add(entry.generation)
        if generations != set(range(trend.first_generation + 1, trend.last_generation + 1)):
            raise LongitudinalEvolutionError("survival ledger generations are not contiguous")
        if ledger.entries != tuple(sorted(
            ledger.entries, key=lambda x: (x.generation, x.candidate_id, x.strategy_id)
        )):
            raise LongitudinalEvolutionError("survival ledger ordering invalid")
        expected_ledger = _digest({
            "previous": ledger.previous_ledger_digest,
            "previous_generation": ledger.previous_generation,
            "entries": [asdict(item) for item in ledger.entries],
            "proposal_only": ledger.proposal_only,
        })
        if expected_ledger != ledger.ledger_digest:
            raise LongitudinalEvolutionError("survival ledger digest mismatch")

        payload = {
            "parent_readiness": trend.parent_readiness_digest,
            "trend": trend.report_digest,
            "audit": audit.audit_digest,
            "attribution": attribution.report_digest,
            "ledger": ledger.ledger_digest,
            "first": trend.first_generation,
            "last": trend.last_generation,
            "proposal_only": True,
        }
        digest = _digest(payload)
        signature = sign_certificate(digest)
        _signed(digest, signature, verify_certificate_signature, "Stage 190 certificate")
        ready = (
            not trend.regressions and audit.passed
            and attribution.unsupported_claim_count == 0
            and "unknown" not in attribution.supported_categories
        )
        return MultiGenerationEvolutionCertificate(
            trend.first_generation, trend.last_generation, trend.parent_readiness_digest,
            trend.report_digest, audit.audit_digest, attribution.report_digest,
            ledger.ledger_digest, digest, signature, ready,
        )


__all__ = [
    "LongitudinalEvolutionError", "stage185_checkpoint_verifier", "GenerationSnapshot", "LongitudinalTrendReport",
    "Stage186LongitudinalTrendAnalyzer", "GeneralizationAuditEvidence",
    "GeneralizationAuditReport", "Stage187GeneralizationAuditor", "RegressionClaim",
    "RegressionAttributionReport", "Stage188RegressionAttributor", "SurvivalLedgerEntry",
    "MultiGenerationSurvivalLedger", "Stage189SurvivalLedger",
    "MultiGenerationEvolutionCertificate", "Stage190LongitudinalCertificatePackager",
]
