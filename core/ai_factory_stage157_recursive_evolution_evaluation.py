"""Stage 157: signed longitudinal evaluation for recursive model evolution.

This module measures generation-to-generation progress and emits bounded strategy
recommendations only. It does not execute experiments, mutate weights, or advance
or activate generations.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage156_authenticated_knowledge_transfer import GenerationKnowledge

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class RecursiveEvaluationError(ValueError):
    """Raised when longitudinal evaluation evidence is invalid or unsafe."""


class EvolutionVerdict:
    IMPROVED = "improved"
    STAGNANT = "stagnant"
    REGRESSED = "regressed"
    MIXED = "mixed"


@dataclass(frozen=True)
class SignedGenerationEvaluation:
    generation: int
    transfer_id: str
    transfer_record_digest: str
    artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    evidence_digest: str
    fitness: Fitness
    signature: str


@dataclass(frozen=True)
class EvolutionStrategyRecommendation:
    recommendation_id: str
    after_generation: int
    verdict: str
    actions: tuple[str, ...]
    rationale: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    evaluation_suite_digest: str
    digest: str
    proposal_only: bool = True
    execution_authorized: bool = False
    model_mutation_authorized: bool = False
    auto_adoption_authorized: bool = False


@dataclass(frozen=True)
class RecursiveEvolutionSnapshot:
    generations: tuple[int, ...]
    verdicts: tuple[str, ...]
    recommendations: tuple[EvolutionStrategyRecommendation, ...]
    improvement_streak: int
    stagnation_streak: int
    regression_streak: int
    digest: str
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False


def _digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _validate_fitness(value: Fitness, suite: str) -> None:
    if not isinstance(value, Fitness) or value.evaluation_suite_digest != suite:
        raise RecursiveEvaluationError("fitness is not bound to the frozen evaluation suite")
    metrics = (value.accuracy, value.instruction_following, value.safety, value.latency_ms, value.memory_mb)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in metrics):
        raise RecursiveEvaluationError("fitness metrics must be finite numbers")
    if not 0 <= value.accuracy <= 1 or not 0 <= value.instruction_following <= 1 or not 0 <= value.safety <= 1:
        raise RecursiveEvaluationError("quality and safety scores must be in [0, 1]")
    if value.latency_ms <= 0 or value.memory_mb <= 0 or value.regression_count < 0:
        raise RecursiveEvaluationError("resource metrics and regression count are invalid")


def _classify(previous: Fitness, current: Fitness) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if current.safety < 0.95 or current.safety < previous.safety - 0.005:
        reasons.append("safety floor or safety regression")
    if current.accuracy < previous.accuracy - 0.005:
        reasons.append("accuracy regression")
    if current.instruction_following < previous.instruction_following - 0.005:
        reasons.append("instruction-following regression")
    if current.latency_ms > previous.latency_ms * 1.10:
        reasons.append("latency regression exceeds 10%")
    if current.memory_mb > previous.memory_mb * 1.10:
        reasons.append("memory regression exceeds 10%")
    if current.regression_count:
        reasons.append("evaluation suite reports regressions")
    if reasons:
        return EvolutionVerdict.REGRESSED, tuple(reasons)

    deltas = (
        current.accuracy - previous.accuracy,
        current.instruction_following - previous.instruction_following,
        current.safety - previous.safety,
        (previous.latency_ms - current.latency_ms) / previous.latency_ms,
        (previous.memory_mb - current.memory_mb) / previous.memory_mb,
    )
    gains = tuple(x > 0.005 for x in deltas[:3]) + tuple(x > 0.02 for x in deltas[3:])
    losses = tuple(x < -0.005 for x in deltas[:3]) + tuple(x < -0.02 for x in deltas[3:])
    if any(gains) and any(losses):
        return EvolutionVerdict.MIXED, ("measurable trade-offs exist; human review is required",)
    if any(gains):
        return EvolutionVerdict.IMPROVED, ("one or more dimensions improved without a guardrail regression",)
    if any(losses):
        return EvolutionVerdict.MIXED, ("small trade-off detected below hard regression thresholds",)
    return EvolutionVerdict.STAGNANT, ("no material change exceeded the configured noise thresholds",)


class RecursiveEvolutionEvaluator:
    """Bounded append-only ledger of independently signed adjacent-generation results."""

    def __init__(self, *, max_generations: int = 256, max_recommendations: int = 256) -> None:
        for name, value in (("max_generations", max_generations), ("max_recommendations", max_recommendations)):
            if not isinstance(value, int) or isinstance(value, bool) or not 2 <= value <= 4096:
                raise ValueError(f"{name} must be between 2 and 4096")
        self._max_generations = max_generations
        self._max_recommendations = max_recommendations
        self._observations: list[SignedGenerationEvaluation] = []
        self._verdicts: list[str] = []
        self._recommendations: list[EvolutionStrategyRecommendation] = []
        self._seen_evidence: set[str] = set()
        self._suite_digest: str | None = None

    def ingest(
        self,
        *,
        transfer: GenerationKnowledge,
        observation: SignedGenerationEvaluation,
        verify_evaluation: Callable[[SignedGenerationEvaluation], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionStrategyRecommendation | None:
        if hold_active or kill_switch_active or not budget_available:
            raise RecursiveEvaluationError("HOLD, kill switch, or unavailable budget blocks evaluation")
        if not isinstance(transfer, GenerationKnowledge) or not isinstance(observation, SignedGenerationEvaluation):
            raise RecursiveEvaluationError("typed Stage 156 transfer and signed generation evaluation are required")
        if (transfer.pending_human_approval is not True or transfer.generation_advanced is not False
                or transfer.model_activated is not False or transfer.auto_adoption_authorized is not False
                or transfer.production_switch_authorized is not False):
            raise RecursiveEvaluationError("Stage 156 transfer must remain pending and non-authoritative")
        if (observation.generation != transfer.proposed_generation
                or observation.transfer_id != transfer.transfer_id
                or observation.transfer_record_digest != transfer.record_digest
                or observation.artifact_digest != transfer.candidate_artifact_digest
                or observation.evaluation_suite_digest != transfer.evaluation_suite_digest):
            raise RecursiveEvaluationError("generation evaluation does not bind to the exact Stage 156 transfer")
        if (not _digest(observation.transfer_record_digest) or not _digest(observation.artifact_digest)
                or not _digest(observation.evaluation_suite_digest) or not _digest(observation.evidence_digest)
                or not _valid_id(observation.evaluator_id)
                or not isinstance(observation.signature, str) or not observation.signature.strip()
                or len(observation.signature) > 8192):
            raise RecursiveEvaluationError("generation evaluation identity, digest, or signature is invalid")
        _validate_fitness(observation.fitness, observation.evaluation_suite_digest)
        if observation.fitness.safety < 0.95 or observation.fitness.regression_count:
            raise RecursiveEvaluationError("safety floor or evaluation regression blocks longitudinal acceptance")
        if not callable(verify_evaluation) or not verify_evaluation(observation):
            raise RecursiveEvaluationError("independent generation-evaluation signature verification failed")
        if len(self._observations) >= self._max_generations:
            raise RecursiveEvaluationError("generation history capacity reached")
        if self._suite_digest is not None and observation.evaluation_suite_digest != self._suite_digest:
            raise RecursiveEvaluationError("evaluation suite drift; cross-suite comparison is not valid")
        if observation.evidence_digest in self._seen_evidence:
            raise RecursiveEvaluationError("duplicate or replayed generation evidence")
        if self._observations:
            previous = self._observations[-1]
            if observation.generation != previous.generation + 1:
                raise RecursiveEvaluationError("generation observations must be strictly adjacent and ordered")
            if observation.evaluator_id == previous.evaluator_id:
                raise RecursiveEvaluationError("adjacent generations require independent evaluator identities")
            verdict, rationale = _classify(previous.fitness, observation.fitness)
            actions = {
                EvolutionVerdict.IMPROVED: (
                    "preserve the successful strategy as a candidate, not an automatic default",
                    "test a small diversified parameter neighborhood in an isolated sandbox",
                    "re-run the frozen benchmark and an independent safety suite",
                ),
                EvolutionVerdict.STAGNANT: (
                    "propose parent and strategy diversification",
                    "inspect benchmark coverage and measurement noise",
                    "cap the next experiment budget until a measurable gain appears",
                ),
                EvolutionVerdict.REGRESSED: (
                    "block inheritance of the regressed candidate",
                    "retain the last reviewed baseline and investigate the failing dimensions",
                    "require a new independent evaluation before another proposal",
                ),
                EvolutionVerdict.MIXED: (
                    "present the quality-resource trade-off for human review",
                    "design a bounded experiment targeting the regressed dimension",
                    "do not rank the candidate as an overall improvement yet",
                ),
            }[verdict]
            if len(self._recommendations) >= self._max_recommendations:
                raise RecursiveEvaluationError("recommendation capacity reached")
            canonical = {
                "previous_generation": previous.generation,
                "generation": observation.generation,
                "verdict": verdict,
                "rationale": list(rationale),
                "actions": list(actions),
                "evidence": [previous.evidence_digest, observation.evidence_digest],
                "suite": observation.evaluation_suite_digest,
            }
            raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            recommendation = EvolutionStrategyRecommendation(
                recommendation_id=hashlib.sha256(("evolution:" + digest).encode()).hexdigest(),
                after_generation=observation.generation,
                verdict=verdict,
                actions=actions,
                rationale=rationale,
                evidence_digests=(previous.evidence_digest, observation.evidence_digest),
                evaluation_suite_digest=observation.evaluation_suite_digest,
                digest=digest,
            )
            self._recommendations.append(recommendation)
            self._verdicts.append(verdict)
        else:
            recommendation = None

        self._observations.append(observation)
        self._seen_evidence.add(observation.evidence_digest)
        self._suite_digest = observation.evaluation_suite_digest
        return recommendation

    def snapshot(self) -> RecursiveEvolutionSnapshot:
        improvements = 0
        stagnations = 0
        regressions = 0
        for verdict in reversed(self._verdicts):
            if verdict == EvolutionVerdict.IMPROVED and stagnations == 0 and regressions == 0:
                improvements += 1
            else:
                break
        for verdict in reversed(self._verdicts):
            if verdict == EvolutionVerdict.STAGNANT:
                stagnations += 1
            else:
                break
        for verdict in reversed(self._verdicts):
            if verdict == EvolutionVerdict.REGRESSED:
                regressions += 1
            else:
                break
        payload = {
            "generations": [x.generation for x in self._observations],
            "verdicts": self._verdicts,
            "recommendations": [x.digest for x in self._recommendations],
            "suite": self._suite_digest,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return RecursiveEvolutionSnapshot(
            generations=tuple(x.generation for x in self._observations),
            verdicts=tuple(self._verdicts),
            recommendations=tuple(self._recommendations),
            improvement_streak=improvements,
            stagnation_streak=stagnations,
            regression_streak=regressions,
            digest=digest,
        )


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


__all__ = [
    "RecursiveEvaluationError", "EvolutionVerdict", "SignedGenerationEvaluation",
    "EvolutionStrategyRecommendation", "RecursiveEvolutionSnapshot",
    "RecursiveEvolutionEvaluator",
]
