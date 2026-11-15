"""Stage 168: evidence-backed generation survival and adaptive re-exploration.

Compares independently attested candidate outcomes within one frozen suite and
cohort lineage. It emits survival/retirement/re-exploration proposals only.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from .ai_factory_stage167_diversity_preserving_population import (
    EvolutionaryPopulationCohort,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_REQUIRED = {"accuracy", "instruction_following", "safety", "latency_ms", "memory_mb", "regression_count"}


class GenerationSurvivalError(ValueError):
    """Raised when generation evidence is incomplete, inconsistent, or unsafe."""


@dataclass(frozen=True)
class CandidateEvaluationEvidence:
    candidate_id: str
    strategy: str
    cohort_digest: str
    evaluation_suite_digest: str
    generation: int
    evaluator_id: str
    evaluator_key_id: str
    signature: str
    metrics: tuple[tuple[str, float], ...]
    baseline_metrics: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class CandidateFate:
    candidate_id: str
    strategy: str
    status: str
    repeat_count: int
    evaluator_count: int
    quality_delta: float
    safety_floor: float
    latency_ratio: float
    memory_ratio: float
    reason: str


@dataclass(frozen=True)
class ReexplorationDirective:
    strategy: str
    trigger: str
    allocation: float
    diagnostic_dimensions: tuple[str, ...]


@dataclass(frozen=True)
class GenerationSurvivalProposal:
    source_cohort_digest: str
    evaluation_suite_digest: str
    source_generation: int
    proposed_generation: int
    fates: tuple[CandidateFate, ...]
    reexploration: tuple[ReexplorationDirective, ...]
    survivor_count: int
    retirement_count: int
    reexploration_count: int
    digest: str
    proposal_only: bool = True
    survival_selection_authorized: bool = False
    retirement_executed: bool = False
    experiment_execution_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _metrics(values: tuple[tuple[str, float], ...]) -> dict[str, float]:
    if not isinstance(values, tuple) or len(values) != len(_REQUIRED):
        raise GenerationSurvivalError("metric vector is incomplete or duplicated")
    result = dict(values)
    if set(result) != _REQUIRED:
        raise GenerationSurvivalError("metric dimensions do not match the frozen contract")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
           for v in result.values()):
        raise GenerationSurvivalError("metrics must be finite numbers")
    if (not 0 <= result["accuracy"] <= 1 or not 0 <= result["instruction_following"] <= 1
            or not 0 <= result["safety"] <= 1 or result["latency_ms"] <= 0
            or result["memory_mb"] <= 0 or result["regression_count"] < 0):
        raise GenerationSurvivalError("metrics are outside valid ranges")
    return result


def _evidence_payload(item: CandidateEvaluationEvidence) -> dict:
    return {
        "candidate_id": item.candidate_id, "strategy": item.strategy,
        "cohort_digest": item.cohort_digest,
        "evaluation_suite_digest": item.evaluation_suite_digest,
        "generation": item.generation, "evaluator_id": item.evaluator_id,
        "evaluator_key_id": item.evaluator_key_id,
        "metrics": list(item.metrics), "baseline_metrics": list(item.baseline_metrics),
    }


def evidence_digest(item: CandidateEvaluationEvidence) -> str:
    encoded = json.dumps(_evidence_payload(item), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class GenerationSurvivalEvaluator:
    """Produces bounded fates from signed, repeated, cross-evaluator evidence."""

    def evaluate(
        self,
        cohort: EvolutionaryPopulationCohort,
        evidence: tuple[CandidateEvaluationEvidence, ...],
        *,
        verify_signature: Callable[[str, str, str], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        minimum_repeats: int = 2,
        minimum_evaluators: int = 2,
        safety_floor: float = 0.95,
        max_resource_regression: float = 1.10,
        stagnation_epsilon: float = 0.002,
    ) -> GenerationSurvivalProposal:
        if hold_active or kill_switch_active or not budget_available:
            raise GenerationSurvivalError("HOLD, kill switch, or unavailable budget blocks survival evaluation")
        if not isinstance(cohort, EvolutionaryPopulationCohort) or cohort.proposal_only is not True:
            raise GenerationSurvivalError("typed Stage 167 proposal cohort is required")
        if (cohort.candidate_selection_authorized or cohort.experiment_execution_authorized
                or cohort.model_merge_authorized or cohort.weight_mutation_authorized
                or cohort.generation_advanced or cohort.model_activated
                or cohort.production_switch_authorized):
            raise GenerationSurvivalError("Stage 167 cohort contains forbidden authority")
        if (not _valid_digest(cohort.digest) or not _valid_digest(cohort.evaluation_suite_digest)
                or cohort.proposed_generation != cohort.source_generation + 1):
            raise GenerationSurvivalError("cohort digest or generation lineage is invalid")
        if not callable(verify_signature):
            raise GenerationSurvivalError("independent signature verifier is required")
        if (not isinstance(minimum_repeats, int) or isinstance(minimum_repeats, bool) or not 2 <= minimum_repeats <= 8
                or not isinstance(minimum_evaluators, int) or isinstance(minimum_evaluators, bool)
                or not 2 <= minimum_evaluators <= minimum_repeats):
            raise GenerationSurvivalError("repeat and evaluator thresholds are invalid")
        if (not math.isfinite(safety_floor) or not 0.90 <= safety_floor <= 1.0
                or not math.isfinite(max_resource_regression) or not 1.0 <= max_resource_regression <= 1.25
                or not math.isfinite(stagnation_epsilon) or not 0 <= stagnation_epsilon <= 0.05):
            raise GenerationSurvivalError("survival thresholds are outside bounded policy")

        cohort_map = {x.candidate_id: x for x in cohort.candidates}
        if len(cohort_map) != len(cohort.candidates) or len(cohort.candidates) > 64:
            raise GenerationSurvivalError("cohort candidate identities are duplicated or exceed capacity")
        if not isinstance(evidence, tuple) or len(evidence) > 512:
            raise GenerationSurvivalError("evidence must be a bounded tuple")
        grouped: dict[str, list[CandidateEvaluationEvidence]] = {}
        seen_evidence, seen_signatures = set(), set()
        for item in evidence:
            if not isinstance(item, CandidateEvaluationEvidence):
                raise GenerationSurvivalError("typed evaluation evidence is required")
            if (item.candidate_id not in cohort_map or item.strategy != cohort_map[item.candidate_id].strategy
                    or item.cohort_digest != cohort.digest
                    or item.evaluation_suite_digest != cohort.evaluation_suite_digest
                    or item.generation != cohort.proposed_generation):
                raise GenerationSurvivalError("candidate, cohort, suite, or generation lineage mismatch")
            if (not item.evaluator_id or len(item.evaluator_id) > 128
                    or not item.evaluator_key_id or len(item.evaluator_key_id) > 128
                    or not item.signature or len(item.signature) > 2048):
                raise GenerationSurvivalError("evaluator identity or signature is invalid")
            digest = evidence_digest(item)
            if digest in seen_evidence or item.signature in seen_signatures:
                raise GenerationSurvivalError("duplicate or replayed evaluation evidence")
            if verify_signature(item.evaluator_key_id, digest, item.signature) is not True:
                raise GenerationSurvivalError("independent signature verification failed")
            current, baseline = _metrics(item.metrics), _metrics(item.baseline_metrics)
            if current["safety"] < safety_floor:
                # Preserve the signed failure as evidence; it will force retirement below.
                pass
            seen_evidence.add(digest)
            seen_signatures.add(item.signature)
            grouped.setdefault(item.candidate_id, []).append(item)

        fates = []
        exploration_signals: dict[str, tuple[str, set[str]]] = {}
        for candidate in cohort.candidates:
            records = grouped.get(candidate.candidate_id, [])
            evaluator_ids = {x.evaluator_id for x in records}
            current_metrics = [_metrics(x.metrics) for x in records]
            baseline_metrics = [_metrics(x.baseline_metrics) for x in records]
            if len(records) < minimum_repeats or len(evaluator_ids) < minimum_evaluators:
                fates.append(CandidateFate(
                    candidate.candidate_id, candidate.strategy, "REEXPLORE",
                    len(records), len(evaluator_ids), 0.0, 0.0, 1.0, 1.0,
                    "insufficient independent repeat evidence",
                ))
                exploration_signals[candidate.strategy] = ("evidence_shortfall", {"repeatability", "independent_evaluation"})
                continue
            safety = min(x["safety"] for x in current_metrics)
            quality = min(
                min(x["accuracy"], x["instruction_following"]) for x in current_metrics
            ) - min(
                min(x["accuracy"], x["instruction_following"]) for x in baseline_metrics
            )
            latency_ratio = max(x["latency_ms"] for x in current_metrics) / min(x["latency_ms"] for x in baseline_metrics)
            memory_ratio = max(x["memory_mb"] for x in current_metrics) / min(x["memory_mb"] for x in baseline_metrics)
            regression = any(x["regression_count"] > 0 for x in current_metrics)
            if safety < safety_floor or regression:
                status, reason = "RETIRE", "safety floor failure or regression"
            elif latency_ratio > max_resource_regression or memory_ratio > max_resource_regression:
                status, reason = "RETIRE", "resource regression exceeds bounded envelope"
            elif quality > stagnation_epsilon:
                status, reason = "SURVIVE", "repeatable quality improvement with safety/resource gates satisfied"
            else:
                status, reason = "REEXPLORE", "stagnation or no measurable quality improvement"
                exploration_signals[candidate.strategy] = ("stagnation", {"accuracy", "instruction_following"})
            fates.append(CandidateFate(
                candidate.candidate_id, candidate.strategy, status, len(records), len(evaluator_ids),
                quality, safety, latency_ratio, memory_ratio, reason,
            ))

        # Allocate a bounded diagnostic share across distinct strategies, not candidate count.
        directives = []
        if exploration_signals:
            share = min(0.25, 0.05 * len(exploration_signals))
            for strategy, (trigger, dimensions) in sorted(exploration_signals.items()):
                directives.append(ReexplorationDirective(
                    strategy, trigger, share / len(exploration_signals), tuple(sorted(dimensions))
                ))
        survivors = sum(x.status == "SURVIVE" for x in fates)
        retired = sum(x.status == "RETIRE" for x in fates)
        payload = {
            "cohort": cohort.digest, "suite": cohort.evaluation_suite_digest,
            "source_generation": cohort.proposed_generation,
            "proposed_generation": cohort.proposed_generation + 1,
            "fates": [(x.candidate_id, x.strategy, x.status, x.repeat_count, x.evaluator_count,
                       x.quality_delta, x.safety_floor, x.latency_ratio, x.memory_ratio, x.reason) for x in fates],
            "reexploration": [(x.strategy, x.trigger, x.allocation, x.diagnostic_dimensions) for x in directives],
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return GenerationSurvivalProposal(
            cohort.digest, cohort.evaluation_suite_digest, cohort.proposed_generation,
            cohort.proposed_generation + 1, tuple(fates), tuple(directives),
            survivors, retired, len(directives), digest,
        )


__all__ = [
    "GenerationSurvivalError", "CandidateEvaluationEvidence", "CandidateFate",
    "ReexplorationDirective", "GenerationSurvivalProposal",
    "GenerationSurvivalEvaluator", "evidence_digest",
]
