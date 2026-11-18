"""Stages 186-190: bounded, signed longitudinal evolution evidence.

These stages improve evaluation, diagnosis, candidate selection evidence, and knowledge
transfer between generations. They emit proposals/reports only: no model execution,
tensor/weight mutation, parameter merge, generation advancement, registration, activation,
or production traffic switch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Callable, Iterable


class LongitudinalEvolutionError(ValueError):
    """Raised when multi-generation evidence is invalid, incomplete, or unsafe."""


_HEX = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest_ok(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise LongitudinalEvolutionError(f"{label} must be a lowercase SHA-256 digest")


def _id_ok(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise LongitudinalEvolutionError(f"{label} is invalid")


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _bounded_rows(values: Iterable, maximum: int, label: str) -> tuple:
    """Consume at most maximum + 1 items, so infinite iterables fail without unbounded work."""
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise LongitudinalEvolutionError(f"{label} must be iterable") from exc
    rows = []
    for _ in range(maximum + 1):
        try:
            rows.append(next(iterator))
        except StopIteration:
            break
    if len(rows) > maximum:
        raise LongitudinalEvolutionError(f"{label} exceeds maximum {maximum}")
    return tuple(rows)


def _signed(digest: str, signature: str, verifier: Callable[[str, str], bool], label: str) -> None:
    _digest_ok(digest, label + " digest")
    if not isinstance(signature, str) or not signature.strip() or not callable(verifier):
        raise LongitudinalEvolutionError(f"{label} signature verifier or signature is missing")
    if verifier(digest, signature) is not True:
        raise LongitudinalEvolutionError(f"{label} signature verification failed")


@dataclass(frozen=True)
class GenerationSnapshot:
    # candidate_id is the stable lineage identity; artifact_candidate_id changes per generation.
    generation: int
    candidate_id: str
    artifact_candidate_id: str
    parent_candidate_id: str
    parent_readiness_digest: str
    artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    executor_id: str
    trial_id: str
    quality: float
    safety: float
    latency_ms: float
    memory_mb: float
    signature: str


@dataclass(frozen=True)
class LongitudinalTrendReport:
    first_generation: int
    last_generation: int
    candidate_id: str
    artifact_candidate_ids: tuple[str, ...]
    parent_candidate_ids: tuple[str, ...]
    evaluation_suite_digest: str
    snapshot_digests: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    executor_ids: tuple[str, ...]
    trial_ids: tuple[str, ...]
    quality_delta: float
    safety_delta: float
    latency_delta: float
    memory_delta: float
    regressions: tuple[str, ...]
    report_digest: str
    signature: str
    proposal_only: bool = True


class Stage186LongitudinalTrendAnalyzer:
    """Measure quality/safety/cost trends with Stage 185 readiness lineage."""

    def build(
        self,
        snapshots: Iterable[GenerationSnapshot],
        *,
        verify_snapshot: Callable[[GenerationSnapshot], bool],
        verify_parent_readiness: Callable[[GenerationSnapshot], bool],
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
        limits = (minimum_safety, max_quality_drop, max_safety_drop, max_latency_growth, max_memory_growth)
        if any(not _finite_number(x) or x < 0 for x in limits) or minimum_safety > 1:
            raise LongitudinalEvolutionError("invalid trend thresholds")
        if not callable(verify_snapshot) or not callable(verify_parent_readiness) or not callable(sign_report):
            raise LongitudinalEvolutionError("Stage 186 verifiers and signer are required")
        rows = _bounded_rows(snapshots, 32, "generation snapshots")
        if len(rows) < minimum_generations:
            raise LongitudinalEvolutionError("insufficient generation snapshots")
        if any(not isinstance(x, GenerationSnapshot) for x in rows):
            raise LongitudinalEvolutionError("generation snapshot schema is invalid")
        rows = tuple(sorted(rows, key=lambda x: x.generation))
        generations = [x.generation for x in rows]
        if any(type(g) is not int or not 0 <= g < 10**9 for g in generations):
            raise LongitudinalEvolutionError("generation number is invalid")
        if len(set(generations)) != len(rows):
            raise LongitudinalEvolutionError("duplicate generation snapshot")
        if generations != list(range(generations[0], generations[-1] + 1)):
            raise LongitudinalEvolutionError("generation history has gaps")
        if len({x.candidate_id for x in rows}) != 1:
            raise LongitudinalEvolutionError("candidate lineage drift")
        if len({x.artifact_candidate_id for x in rows}) != len(rows):
            raise LongitudinalEvolutionError("artifact candidate replay")
        if len({x.evaluation_suite_digest for x in rows}) != 1:
            raise LongitudinalEvolutionError("evaluation suite drift across generations")
        evaluator_ids = tuple(x.evaluator_id for x in rows)
        executor_ids = tuple(x.executor_id for x in rows)
        trial_ids = tuple(x.trial_id for x in rows)
        if (len(set(evaluator_ids)) != len(rows) or len(set(executor_ids)) != len(rows)
                or len(set(trial_ids)) != len(rows) or set(evaluator_ids) & set(executor_ids)):
            raise LongitudinalEvolutionError("independent evaluator, executor, and trial identities required")
        for index, item in enumerate(rows):
            _id_ok(item.candidate_id, "candidate lineage id")
            _id_ok(item.artifact_candidate_id, "artifact candidate id")
            _id_ok(item.parent_candidate_id, "parent candidate id")
            _id_ok(item.evaluator_id, "evaluator id")
            _id_ok(item.executor_id, "executor id")
            _id_ok(item.trial_id, "trial id")
            _digest_ok(item.parent_readiness_digest, "Stage 185 readiness certificate")
            _digest_ok(item.artifact_digest, "artifact")
            _digest_ok(item.evaluation_suite_digest, "evaluation suite")
            if index and item.parent_candidate_id != rows[index - 1].artifact_candidate_id:
                raise LongitudinalEvolutionError("generation parent candidate lineage mismatch")
            metrics = (item.quality, item.safety, item.latency_ms, item.memory_mb)
            if any(not _finite_number(v) for v in metrics):
                raise LongitudinalEvolutionError("non-finite generation metric")
            if not (0 <= item.quality <= 1 and 0 <= item.safety <= 1
                    and item.latency_ms >= 0 and item.memory_mb >= 0):
                raise LongitudinalEvolutionError("generation metric outside valid range")
            if not item.signature or verify_snapshot(item) is not True:
                raise LongitudinalEvolutionError("generation snapshot signature verification failed")
            if verify_parent_readiness(item) is not True:
                raise LongitudinalEvolutionError("Stage 185 parent readiness signature or lineage verification failed")
        first, last = rows[0], rows[-1]
        quality_delta = last.quality - first.quality
        safety_delta = last.safety - first.safety
        latency_delta = last.latency_ms - first.latency_ms
        memory_delta = last.memory_mb - first.memory_mb
        regressions = []
        if min(x.safety for x in rows) < minimum_safety:
            regressions.append("safety_floor")
        if quality_delta < -max_quality_drop:
            regressions.append("quality_decline")
        if safety_delta < -max_safety_drop:
            regressions.append("safety_decline")
        if first.latency_ms > 0 and last.latency_ms > first.latency_ms * (1 + max_latency_growth):
            regressions.append("latency_growth")
        if first.memory_mb > 0 and last.memory_mb > first.memory_mb * (1 + max_memory_growth):
            regressions.append("memory_growth")
        snapshot_digests = tuple(_digest(asdict(x)) for x in rows)
        artifact_candidate_ids = tuple(x.artifact_candidate_id for x in rows)
        parent_candidate_ids = tuple(x.parent_candidate_id for x in rows)
        payload = {
            "first": first.generation, "last": last.generation, "candidate": first.candidate_id,
            "artifact_candidates": artifact_candidate_ids, "parents": parent_candidate_ids,
            "suite": first.evaluation_suite_digest, "snapshots": snapshot_digests,
            "evaluators": evaluator_ids, "executors": executor_ids, "trials": trial_ids,
            "quality_delta": quality_delta, "safety_delta": safety_delta,
            "latency_delta": latency_delta, "memory_delta": memory_delta,
            "regressions": tuple(regressions), "proposal_only": True,
        }
        report_digest = _digest(payload)
        signature = sign_report(report_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise LongitudinalEvolutionError("Stage 186 report signing failed")
        return LongitudinalTrendReport(
            first.generation, last.generation, first.candidate_id, artifact_candidate_ids,
            parent_candidate_ids, first.evaluation_suite_digest, snapshot_digests,
            evaluator_ids, executor_ids, trial_ids, quality_delta, safety_delta,
            latency_delta, memory_delta, tuple(regressions), report_digest, signature,
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
    executor_id: str
    trial_id: str
    signature: str


@dataclass(frozen=True)
class GeneralizationAuditReport:
    trend_report_digest: str
    audit_evidence_digest: str
    passed: bool
    coverage: float
    audit_digest: str
    signature: str
    proposal_only: bool = True


class Stage187GeneralizationAuditor:
    """Require a signed, disjoint holdout audit from an independent evaluator/executor."""

    def build(
        self,
        trend: LongitudinalTrendReport,
        evidence: GeneralizationAuditEvidence,
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_evidence: Callable[[GeneralizationAuditEvidence], bool],
        sign_report: Callable[[str], str],
        minimum_coverage: float = 0.95,
        hold_active: bool = False,
    ) -> GeneralizationAuditReport:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 187")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        if not isinstance(evidence, GeneralizationAuditEvidence):
            raise LongitudinalEvolutionError("generalization evidence schema is invalid")
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
        _id_ok(evidence.evaluator_id, "generalization evaluator")
        _id_ok(evidence.executor_id, "generalization executor")
        _id_ok(evidence.trial_id, "generalization trial")
        prior_ids = set(trend.evaluator_ids) | set(trend.executor_ids)
        if (evidence.evaluator_id == evidence.executor_id
                or evidence.evaluator_id in prior_ids or evidence.executor_id in prior_ids
                or evidence.trial_id in trend.trial_ids):
            raise LongitudinalEvolutionError("generalization evaluator/executor must be independent")
        if (not _finite_number(minimum_coverage) or not 0 <= minimum_coverage <= 1
                or not _finite_number(evidence.coverage) or not 0 <= evidence.coverage <= 1):
            raise LongitudinalEvolutionError("invalid holdout coverage")
        if any(type(flag) is not bool for flag in (
            evidence.training_holdout_disjoint, evidence.holdout_never_used_for_training,
            evidence.contamination_check_passed,
        )):
            raise LongitudinalEvolutionError("holdout attestations must be booleans")
        if not callable(verify_evidence) or not evidence.signature or verify_evidence(evidence) is not True:
            raise LongitudinalEvolutionError("generalization evidence signature verification failed")
        passed = (
            evidence.training_holdout_disjoint and evidence.holdout_never_used_for_training
            and evidence.contamination_check_passed and evidence.coverage >= minimum_coverage
        )
        evidence_digest = _digest(asdict(evidence))
        payload = {
            "trend": trend.report_digest, "evidence": evidence_digest,
            "passed": passed, "coverage": evidence.coverage, "proposal_only": True,
        }
        audit_digest = _digest(payload)
        signature = sign_report(audit_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise LongitudinalEvolutionError("Stage 187 report signing failed")
        return GeneralizationAuditReport(
            trend.report_digest, evidence_digest, passed, evidence.coverage, audit_digest, signature
        )


@dataclass(frozen=True)
class RegressionClaim:
    category: str
    affected_generation: int
    candidate_id: str
    causal_evidence_digest: str
    evaluator_id: str
    executor_id: str
    trial_id: str
    signature: str


@dataclass(frozen=True)
class RegressionAttributionReport:
    trend_report_digest: str
    claim_digests: tuple[str, ...]
    supported_categories: tuple[str, ...]
    unsupported_claim_count: int
    report_digest: str
    signature: str
    proposal_only: bool = True


class Stage188RegressionAttributor:
    """Keep unknown causes explicit; forged or mis-lineaged claims fail closed."""

    ALLOWED = frozenset({
        "data_drift", "evaluation_drift", "resource_pressure",
        "candidate_regression", "toolchain_change", "unknown",
    })

    def build(
        self,
        trend: LongitudinalTrendReport,
        claims: Iterable[RegressionClaim],
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_claim: Callable[[RegressionClaim], bool],
        sign_report: Callable[[str], str],
        hold_active: bool = False,
    ) -> RegressionAttributionReport:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 188")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        if not callable(verify_claim) or not callable(sign_report):
            raise LongitudinalEvolutionError("Stage 188 verifiers and signer are required")
        rows = _bounded_rows(claims, 64, "regression claims")
        if any(not isinstance(x, RegressionClaim) for x in rows):
            raise LongitudinalEvolutionError("regression claim schema is invalid")
        evaluator_ids = set()
        executor_ids = set()
        trial_ids = set()
        accepted_digests = []
        supported = set()
        unsupported = 0
        prior_ids = set(trend.evaluator_ids) | set(trend.executor_ids)
        for claim in rows:
            _id_ok(claim.candidate_id, "claim candidate")
            _id_ok(claim.evaluator_id, "claim evaluator")
            _id_ok(claim.executor_id, "claim executor")
            _id_ok(claim.trial_id, "claim trial")
            _digest_ok(claim.causal_evidence_digest, "causal evidence")
            if claim.candidate_id != trend.candidate_id:
                raise LongitudinalEvolutionError("regression claim candidate lineage mismatch")
            if type(claim.affected_generation) is not int or not (
                trend.first_generation <= claim.affected_generation <= trend.last_generation
            ):
                raise LongitudinalEvolutionError("regression claim generation lineage mismatch")
            if (claim.evaluator_id == claim.executor_id or claim.evaluator_id in prior_ids
                    or claim.executor_id in prior_ids or claim.evaluator_id in evaluator_ids
                    or claim.executor_id in executor_ids or claim.evaluator_id in executor_ids
                    or claim.executor_id in evaluator_ids or claim.trial_id in trial_ids
                    or claim.trial_id in trend.trial_ids):
                raise LongitudinalEvolutionError("regression claim evaluator/executor/trial replay")
            if not claim.signature or verify_claim(claim) is not True:
                raise LongitudinalEvolutionError("regression claim signature verification failed")
            evaluator_ids.add(claim.evaluator_id)
            executor_ids.add(claim.executor_id)
            trial_ids.add(claim.trial_id)
            accepted_digests.append(_digest(asdict(claim)))
            if claim.category in self.ALLOWED and claim.category != "unknown":
                supported.add(claim.category)
            else:
                unsupported += 1
        claim_digests = tuple(sorted(accepted_digests))
        supported_categories = tuple(sorted(supported))
        payload = {
            "trend": trend.report_digest, "claims": claim_digests,
            "categories": supported_categories, "unsupported": unsupported, "proposal_only": True,
        }
        report_digest = _digest(payload)
        signature = sign_report(report_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise LongitudinalEvolutionError("Stage 188 report signing failed")
        return RegressionAttributionReport(
            trend.report_digest, claim_digests, supported_categories, unsupported, report_digest, signature
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
    previous_ledger_signature: str
    previous_generation: int
    entries: tuple[SurvivalLedgerEntry, ...]
    ledger_digest: str
    signature: str
    proposal_only: bool = True


class Stage189SurvivalLedger:
    """Append a signed, contiguous, evidence-verified record of evolutionary outcomes."""

    OUTCOMES = frozenset({"survived", "retired_proposal", "reexplore_proposal"})

    def build(
        self,
        *,
        previous_ledger_digest: str,
        previous_ledger_signature: str,
        previous_generation: int,
        entries: Iterable[SurvivalLedgerEntry],
        verify_previous_ledger: Callable[[str, str], bool],
        verify_entry: Callable[[SurvivalLedgerEntry], bool],
        sign_report: Callable[[str], str],
        max_entries: int = 128,
        hold_active: bool = False,
    ) -> MultiGenerationSurvivalLedger:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 189")
        _digest_ok(previous_ledger_digest, "previous ledger")
        if type(previous_generation) is not int or not 0 <= previous_generation < 10**9:
            raise LongitudinalEvolutionError("previous generation is invalid")
        if type(max_entries) is not int or not 1 <= max_entries <= 512:
            raise LongitudinalEvolutionError("ledger bounds invalid")
        _signed(previous_ledger_digest, previous_ledger_signature, verify_previous_ledger, "previous ledger")
        if not callable(verify_entry) or not callable(sign_report):
            raise LongitudinalEvolutionError("Stage 189 verifiers and signer are required")
        rows = _bounded_rows(entries, max_entries, "ledger entries")
        if not rows:
            raise LongitudinalEvolutionError("ledger entry count outside bounds")
        if any(not isinstance(x, SurvivalLedgerEntry) for x in rows):
            raise LongitudinalEvolutionError("ledger entry schema is invalid")
        keys = set()
        generations = set()
        for entry in rows:
            if type(entry.generation) is not int or not (
                previous_generation < entry.generation <= previous_generation + 32
            ):
                raise LongitudinalEvolutionError("ledger generation is not a bounded append")
            _id_ok(entry.candidate_id, "ledger candidate")
            _id_ok(entry.strategy_id, "ledger strategy")
            _digest_ok(entry.artifact_digest, "ledger artifact")
            _digest_ok(entry.evidence_digest, "ledger evidence")
            if entry.outcome not in self.OUTCOMES:
                raise LongitudinalEvolutionError("ledger outcome invalid")
            if not entry.signature or verify_entry(entry) is not True:
                raise LongitudinalEvolutionError("ledger entry evidence signature verification failed")
            key = (entry.generation, entry.candidate_id, entry.strategy_id)
            if key in keys:
                raise LongitudinalEvolutionError("duplicate ledger entry")
            keys.add(key)
            generations.add(entry.generation)
        expected_generations = set(range(previous_generation + 1, max(generations) + 1))
        if generations != expected_generations:
            raise LongitudinalEvolutionError("ledger generation history has gaps")
        ordered = tuple(sorted(rows, key=lambda x: (x.generation, x.candidate_id, x.strategy_id)))
        payload = {
            "previous": previous_ledger_digest, "previous_signature": previous_ledger_signature,
            "previous_generation": previous_generation, "entries": [asdict(x) for x in ordered],
            "proposal_only": True,
        }
        ledger_digest = _digest(payload)
        signature = sign_report(ledger_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise LongitudinalEvolutionError("Stage 189 ledger signing failed")
        return MultiGenerationSurvivalLedger(
            previous_ledger_digest, previous_ledger_signature, previous_generation,
            ordered, ledger_digest, signature,
        )


@dataclass(frozen=True)
class MultiGenerationEvolutionCertificate:
    first_generation: int
    last_generation: int
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
    """Verify all prior stages and issue a non-authorizing human-review certificate."""

    def build(
        self,
        trend: LongitudinalTrendReport,
        audit: GeneralizationAuditReport,
        attribution: RegressionAttributionReport,
        ledger: MultiGenerationSurvivalLedger,
        *,
        verify_trend_signature: Callable[[str, str], bool],
        verify_audit_signature: Callable[[str, str], bool],
        verify_attribution_signature: Callable[[str, str], bool],
        verify_ledger_signature: Callable[[str, str], bool],
        verify_ledger_predecessor: Callable[[str, str], bool],
        verify_ledger_entry: Callable[[SurvivalLedgerEntry], bool],
        sign_certificate: Callable[[str], str],
        hold_active: bool = False,
    ) -> MultiGenerationEvolutionCertificate:
        if hold_active:
            raise LongitudinalEvolutionError("HOLD blocks Stage 190")
        _verify_trend(trend)
        _signed(trend.report_digest, trend.signature, verify_trend_signature, "Stage 186")
        if not isinstance(audit, GeneralizationAuditReport) or not isinstance(attribution, RegressionAttributionReport):
            raise LongitudinalEvolutionError("upstream report schema is invalid")
        if (type(audit.proposal_only) is not bool or audit.proposal_only is not True
                or type(attribution.proposal_only) is not bool or attribution.proposal_only is not True):
            raise LongitudinalEvolutionError("all upstream reports must remain proposal-only")
        if type(audit.passed) is not bool or not _finite_number(audit.coverage) or not 0 <= audit.coverage <= 1:
            raise LongitudinalEvolutionError("generalization audit coverage or result is invalid")
        if type(attribution.unsupported_claim_count) is not int or not 0 <= attribution.unsupported_claim_count <= 64:
            raise LongitudinalEvolutionError("unsupported claim count is outside bounds")
        if (len(attribution.claim_digests) > 64
                or len(set(attribution.claim_digests)) != len(attribution.claim_digests)
                or any(not isinstance(value, str) or not _HEX.fullmatch(value)
                       for value in attribution.claim_digests)):
            raise LongitudinalEvolutionError("regression claim digest set is invalid")
        if (attribution.supported_categories != tuple(sorted(set(attribution.supported_categories)))
                or any(value not in Stage188RegressionAttributor.ALLOWED or value == "unknown"
                       for value in attribution.supported_categories)):
            raise LongitudinalEvolutionError("regression attribution categories are invalid")
        _signed(audit.audit_digest, audit.signature, verify_audit_signature, "Stage 187")
        _signed(attribution.report_digest, attribution.signature, verify_attribution_signature, "Stage 188")
        if audit.trend_report_digest != trend.report_digest:
            raise LongitudinalEvolutionError("generalization audit lineage mismatch")
        expected_audit = _digest({
            "trend": audit.trend_report_digest, "evidence": audit.audit_evidence_digest,
            "passed": audit.passed, "coverage": audit.coverage, "proposal_only": audit.proposal_only,
        })
        if expected_audit != audit.audit_digest:
            raise LongitudinalEvolutionError("generalization audit digest mismatch")
        _digest_ok(audit.audit_evidence_digest, "generalization evidence")
        if not audit.passed:
            raise LongitudinalEvolutionError("generalization audit failed")
        if attribution.trend_report_digest != trend.report_digest:
            raise LongitudinalEvolutionError("regression attribution lineage mismatch")
        expected_attribution = _digest({
            "trend": attribution.trend_report_digest, "claims": attribution.claim_digests,
            "categories": attribution.supported_categories,
            "unsupported": attribution.unsupported_claim_count, "proposal_only": attribution.proposal_only,
        })
        if expected_attribution != attribution.report_digest:
            raise LongitudinalEvolutionError("regression attribution digest mismatch")
        if (not isinstance(ledger, MultiGenerationSurvivalLedger) or type(ledger.proposal_only) is not bool
                or ledger.proposal_only is not True):
            raise LongitudinalEvolutionError("survival ledger is not proposal-only")
        if not isinstance(ledger.entries, tuple) or not 1 <= len(ledger.entries) <= 512:
            raise LongitudinalEvolutionError("survival ledger bounds invalid")
        if any(not isinstance(x, SurvivalLedgerEntry) for x in ledger.entries):
            raise LongitudinalEvolutionError("survival ledger entry schema is invalid")
        _signed(ledger.ledger_digest, ledger.signature, verify_ledger_signature, "Stage 189")
        _signed(ledger.previous_ledger_digest, ledger.previous_ledger_signature,
                verify_ledger_predecessor, "Stage 189 predecessor")
        if not callable(verify_ledger_entry):
            raise LongitudinalEvolutionError("Stage 189 entry verifier is required")
        expected_ledger = _digest({
            "previous": ledger.previous_ledger_digest,
            "previous_signature": ledger.previous_ledger_signature,
            "previous_generation": ledger.previous_generation,
            "entries": [asdict(x) for x in ledger.entries],
            "proposal_only": ledger.proposal_only,
        })
        if expected_ledger != ledger.ledger_digest:
            raise LongitudinalEvolutionError("survival ledger digest mismatch")
        if type(ledger.previous_generation) is not int or not 0 <= ledger.previous_generation < 10**9:
            raise LongitudinalEvolutionError("survival ledger previous generation is invalid")
        keys = set()
        generations = set()
        for entry in ledger.entries:
            _id_ok(entry.candidate_id, "ledger candidate")
            _id_ok(entry.strategy_id, "ledger strategy")
            _digest_ok(entry.artifact_digest, "ledger artifact")
            _digest_ok(entry.evidence_digest, "ledger evidence")
            if not entry.signature or verify_ledger_entry(entry) is not True:
                raise LongitudinalEvolutionError("survival ledger entry signature verification failed")
            if entry.candidate_id != trend.candidate_id:
                raise LongitudinalEvolutionError("survival ledger candidate lineage mismatch")
            if type(entry.generation) is not int or not (
                ledger.previous_generation < entry.generation <= ledger.previous_generation + 32
            ):
                raise LongitudinalEvolutionError("survival ledger generation is not a bounded append")
            if not trend.first_generation <= entry.generation <= trend.last_generation:
                raise LongitudinalEvolutionError("survival ledger generation outside verified trend window")
            if entry.outcome not in Stage189SurvivalLedger.OUTCOMES:
                raise LongitudinalEvolutionError("survival ledger outcome invalid")
            key = (entry.generation, entry.candidate_id, entry.strategy_id)
            if key in keys:
                raise LongitudinalEvolutionError("duplicate survival ledger entry")
            keys.add(key)
            generations.add(entry.generation)
        expected_start = max(trend.first_generation, ledger.previous_generation + 1)
        expected_generations = set(range(expected_start, trend.last_generation + 1))
        if generations != expected_generations:
            raise LongitudinalEvolutionError("survival ledger generation history has gaps or is incomplete")
        if ledger.entries != tuple(sorted(ledger.entries, key=lambda x: (x.generation, x.candidate_id, x.strategy_id))):
            raise LongitudinalEvolutionError("survival ledger ordering invalid")
        if not callable(sign_certificate):
            raise LongitudinalEvolutionError("Stage 190 certificate signer is required")
        payload = {
            "trend": trend.report_digest, "audit": audit.audit_digest,
            "attribution": attribution.report_digest, "ledger": ledger.ledger_digest,
            "first": trend.first_generation, "last": trend.last_generation, "proposal_only": True,
        }
        certificate_digest = _digest(payload)
        signature = sign_certificate(certificate_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise LongitudinalEvolutionError("Stage 190 certificate signing failed")
        ready = (
            not trend.regressions and audit.passed and attribution.unsupported_claim_count == 0
            and "unknown" not in attribution.supported_categories
        )
        return MultiGenerationEvolutionCertificate(
            trend.first_generation, trend.last_generation, trend.report_digest,
            audit.audit_digest, attribution.report_digest, ledger.ledger_digest,
            certificate_digest, signature, ready,
        )


def _verify_trend(trend: LongitudinalTrendReport) -> None:
    if not isinstance(trend, LongitudinalTrendReport) or trend.proposal_only is not True:
        raise LongitudinalEvolutionError("invalid longitudinal trend report")
    if (type(trend.first_generation) is not int or type(trend.last_generation) is not int
            or trend.last_generation < trend.first_generation + 2
            or trend.last_generation - trend.first_generation >= 32):
        raise LongitudinalEvolutionError("invalid longitudinal trend generation window")
    _id_ok(trend.candidate_id, "trend candidate lineage")
    _digest_ok(trend.evaluation_suite_digest, "trend suite")
    _digest_ok(trend.report_digest, "trend report")
    if not isinstance(trend.signature, str) or not trend.signature.strip():
        raise LongitudinalEvolutionError("trend signature is missing")
    expected_length = trend.last_generation - trend.first_generation + 1
    collections = (
        trend.artifact_candidate_ids, trend.parent_candidate_ids, trend.snapshot_digests,
        trend.evaluator_ids, trend.executor_ids, trend.trial_ids,
    )
    if any(not isinstance(values, tuple) or len(values) != expected_length for values in collections):
        raise LongitudinalEvolutionError("trend lineage collection length mismatch")
    if (len(set(trend.artifact_candidate_ids)) != expected_length
            or len(set(trend.evaluator_ids)) != expected_length
            or len(set(trend.executor_ids)) != expected_length
            or len(set(trend.trial_ids)) != expected_length
            or set(trend.evaluator_ids) & set(trend.executor_ids)):
        raise LongitudinalEvolutionError("trend independent identity or replay check failed")
    for index, value in enumerate(trend.snapshot_digests):
        _digest_ok(value, "trend snapshot")
        _id_ok(trend.artifact_candidate_ids[index], "trend artifact candidate")
        _id_ok(trend.parent_candidate_ids[index], "trend parent candidate")
        _id_ok(trend.evaluator_ids[index], "trend evaluator")
        _id_ok(trend.executor_ids[index], "trend executor")
        _id_ok(trend.trial_ids[index], "trend trial")
        if index and trend.parent_candidate_ids[index] != trend.artifact_candidate_ids[index - 1]:
            raise LongitudinalEvolutionError("trend parent lineage mismatch")
    if any(not _finite_number(v) for v in (
        trend.quality_delta, trend.safety_delta, trend.latency_delta, trend.memory_delta
    )):
        raise LongitudinalEvolutionError("trend metrics are invalid")
    if not isinstance(trend.regressions, tuple) or len(set(trend.regressions)) != len(trend.regressions):
        raise LongitudinalEvolutionError("trend regression flags are invalid")
    payload = {
        "first": trend.first_generation, "last": trend.last_generation, "candidate": trend.candidate_id,
        "artifact_candidates": trend.artifact_candidate_ids, "parents": trend.parent_candidate_ids,
        "suite": trend.evaluation_suite_digest, "snapshots": trend.snapshot_digests,
        "evaluators": trend.evaluator_ids, "executors": trend.executor_ids, "trials": trend.trial_ids,
        "quality_delta": trend.quality_delta, "safety_delta": trend.safety_delta,
        "latency_delta": trend.latency_delta, "memory_delta": trend.memory_delta,
        "regressions": trend.regressions, "proposal_only": trend.proposal_only,
    }
    if _digest(payload) != trend.report_digest:
        raise LongitudinalEvolutionError("trend report digest mismatch")


__all__ = [
    "LongitudinalEvolutionError", "GenerationSnapshot", "LongitudinalTrendReport",
    "Stage186LongitudinalTrendAnalyzer", "GeneralizationAuditEvidence", "GeneralizationAuditReport",
    "Stage187GeneralizationAuditor", "RegressionClaim", "RegressionAttributionReport",
    "Stage188RegressionAttributor", "SurvivalLedgerEntry", "MultiGenerationSurvivalLedger",
    "Stage189SurvivalLedger", "MultiGenerationEvolutionCertificate",
    "Stage190LongitudinalCertificatePackager",
]
