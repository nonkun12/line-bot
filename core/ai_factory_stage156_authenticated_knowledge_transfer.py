"""Stage 156: authenticated, bounded knowledge transfer between model generations.

Only an accepted Stage 155 experiment with independently re-verified evidence can
produce a next-generation proposal. This module never advances or activates a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlan
from .ai_factory_stage155_isolated_merge_experiments import MergeExperimentOutcome

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class KnowledgeTransferError(ValueError):
    """Raised when authenticated generation knowledge cannot safely transfer."""


@dataclass(frozen=True)
class Stage156SignedEvidence:
    """Evidence envelope supplied by the independent Stage 155 evaluator."""
    outcome_digest: str
    evidence_digest: str
    artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    source_generation: int
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    fitness: Fitness
    signature: str


@dataclass(frozen=True)
class GenerationKnowledge:
    transfer_id: str
    source_generation: int
    proposed_generation: int
    source_candidate_id: str
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    recipe_digest: str
    strategy: str
    fitness: Fitness
    outcome_digest: str
    evidence_digest: str
    evaluator_id: str
    lessons: tuple[str, ...]
    record_digest: str
    pending_human_approval: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    auto_adoption_authorized: bool = False
    production_switch_authorized: bool = False


@dataclass(frozen=True)
class KnowledgeTransferSnapshot:
    records: tuple[GenerationKnowledge, ...]
    source_generations: tuple[int, ...]
    proposed_generations: tuple[int, ...]
    digest: str
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _validate_fitness(value: Fitness, suite: str) -> None:
    if not isinstance(value, Fitness) or value.evaluation_suite_digest != suite:
        raise KnowledgeTransferError("fitness is not bound to the frozen evaluation suite")
    numeric = (value.accuracy, value.instruction_following, value.safety, value.latency_ms, value.memory_mb)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in numeric):
        raise KnowledgeTransferError("fitness metrics must be numeric")
    if any(not __import__("math").isfinite(x) for x in numeric):
        raise KnowledgeTransferError("fitness metrics must be finite")
    if not 0 <= value.accuracy <= 1 or not 0 <= value.instruction_following <= 1 or not 0 <= value.safety <= 1:
        raise KnowledgeTransferError("fitness scores must be within [0, 1]")
    if value.latency_ms < 0 or value.memory_mb < 0 or value.regression_count < 0:
        raise KnowledgeTransferError("resource and regression metrics must be non-negative")


class AuthenticatedKnowledgeTransfer:
    """Append-only in-memory transfer ledger; all records remain human-review proposals."""

    def __init__(self, *, max_records: int = 128, max_generation_gap: int = 1) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= 4096:
            raise ValueError("max_records must be between 1 and 4096")
        if not isinstance(max_generation_gap, int) or isinstance(max_generation_gap, bool) or max_generation_gap != 1:
            raise ValueError("only adjacent-generation transfer is supported")
        self._max_records = max_records
        self._records: list[GenerationKnowledge] = []
        self._outcomes: set[str] = set()
        self._suite_by_generation: dict[int, str] = {}

    def ingest(
        self,
        *,
        outcome: MergeExperimentOutcome,
        plan: MergeEvaluationPlan,
        evidence: Stage156SignedEvidence,
        baseline_fitness: Fitness,
        verify_stage155_evidence: Callable[[Stage156SignedEvidence], bool],
        expected_suite_digest: str,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> GenerationKnowledge:
        if hold_active or kill_switch_active or not budget_available:
            raise KnowledgeTransferError("HOLD, kill switch, or unavailable budget blocks knowledge transfer")
        if not isinstance(outcome, MergeExperimentOutcome) or not isinstance(plan, MergeEvaluationPlan):
            raise KnowledgeTransferError("typed Stage 155 outcome and Stage 154 plan are required")
        if not isinstance(evidence, Stage156SignedEvidence):
            raise KnowledgeTransferError("typed signed Stage 155 evidence envelope is required")
        if outcome.accepted_for_next_generation is not True or outcome.proposal_only is not True:
            raise KnowledgeTransferError("only an accepted proposal-only Stage 155 outcome may transfer")
        if (outcome.generation_advanced is not False or outcome.model_activated is not False
                or outcome.production_switch_authorized is not False):
            raise KnowledgeTransferError("Stage 155 outcome contains forbidden authority")
        if (plan.execution_authorized is not False or plan.merge_authorized is not False
                or plan.activation_authorized is not False or plan.independent_evaluation_required is not True):
            raise KnowledgeTransferError("Stage 154 plan must remain non-authoritative")
        if not all(_valid_digest(x) for x in (
            outcome.recipe_digest, outcome.output_artifact_digest,
            outcome.evaluation_evidence_digest, outcome.outcome_digest,
            plan.recipe_digest, plan.evaluation_suite_digest,
            plan.candidate_artifact_digest, expected_suite_digest,
            evidence.outcome_digest, evidence.evidence_digest,
            evidence.artifact_digest, evidence.evaluation_suite_digest,
        )):
            raise KnowledgeTransferError("one or more evidence digests are invalid")
        if (outcome.plan_id != plan.plan_id or outcome.recipe_digest != plan.recipe_digest
                or outcome.output_artifact_digest != evidence.artifact_digest
                or outcome.evaluation_evidence_digest != evidence.evidence_digest
                or evidence.outcome_digest != outcome.outcome_digest
                or evidence.evaluation_suite_digest != expected_suite_digest
                or plan.evaluation_suite_digest != expected_suite_digest):
            raise KnowledgeTransferError("outcome, plan, artifact, evidence, or frozen suite binding mismatch")
        if (not _valid_id(outcome.evaluator_id) or evidence.evaluator_id != outcome.evaluator_id
                or not isinstance(evidence.signature, str) or not evidence.signature.strip()
                or len(evidence.signature) > 8192):
            raise KnowledgeTransferError("independent evaluator identity or signature is invalid")
        if evidence.source_generation != plan.generation or plan.generation < 0:
            raise KnowledgeTransferError("source generation does not match the immutable plan")
        if (evidence.parent_model_ids != plan.parent_model_ids
                or evidence.parent_artifact_digests != plan.parent_artifact_digests
                or len(evidence.parent_model_ids) < 2
                or len(evidence.parent_model_ids) != len(evidence.parent_artifact_digests)
                or any(not _valid_id(x) for x in evidence.parent_model_ids)
                or any(not _valid_digest(x) for x in evidence.parent_artifact_digests)):
            raise KnowledgeTransferError("parent model lineage does not match the exact Stage 154 plan")
        _validate_fitness(evidence.fitness, expected_suite_digest)
        _validate_fitness(baseline_fitness, expected_suite_digest)
        if evidence.fitness.safety < 0.95 or evidence.fitness.safety < baseline_fitness.safety:
            raise KnowledgeTransferError("safety floor or baseline regression blocks transfer")
        if evidence.fitness.accuracy < baseline_fitness.accuracy:
            raise KnowledgeTransferError("accuracy regression blocks transfer")
        if evidence.fitness.instruction_following < baseline_fitness.instruction_following:
            raise KnowledgeTransferError("instruction-following regression blocks transfer")
        if evidence.fitness.latency_ms > baseline_fitness.latency_ms * 1.10:
            raise KnowledgeTransferError("latency regression exceeds 10%")
        if evidence.fitness.memory_mb > baseline_fitness.memory_mb * 1.10:
            raise KnowledgeTransferError("memory regression exceeds 10%")
        if evidence.fitness.regression_count != 0:
            raise KnowledgeTransferError("evaluation regressions block transfer")
        improved = (
            evidence.fitness.accuracy > baseline_fitness.accuracy
            or evidence.fitness.instruction_following > baseline_fitness.instruction_following
            or evidence.fitness.safety > baseline_fitness.safety
            or evidence.fitness.latency_ms < baseline_fitness.latency_ms
            or evidence.fitness.memory_mb < baseline_fitness.memory_mb
        )
        if not improved:
            raise KnowledgeTransferError("no measurable improvement to transfer")
        if not callable(verify_stage155_evidence) or not verify_stage155_evidence(evidence):
            raise KnowledgeTransferError("Stage 155 signature/evidence verification failed")

        source_generation = plan.generation
        proposed_generation = source_generation + 1
        if source_generation in self._suite_by_generation and self._suite_by_generation[source_generation] != expected_suite_digest:
            raise KnowledgeTransferError("evaluation suite drift within source generation")
        if self._records and source_generation < max(x.source_generation for x in self._records):
            raise KnowledgeTransferError("out-of-order generation transfer is rejected")
        if outcome.outcome_digest in self._outcomes:
            raise KnowledgeTransferError("duplicate or replayed Stage 155 outcome")
        if len(self._records) >= self._max_records:
            raise KnowledgeTransferError("knowledge transfer capacity reached")

        lessons = []
        if evidence.fitness.accuracy > baseline_fitness.accuracy:
            lessons.append("retain strategy: accuracy improved")
        if evidence.fitness.instruction_following > baseline_fitness.instruction_following:
            lessons.append("retain strategy: instruction following improved")
        if evidence.fitness.safety > baseline_fitness.safety:
            lessons.append("retain strategy: safety improved")
        if evidence.fitness.latency_ms < baseline_fitness.latency_ms:
            lessons.append("retain strategy: latency improved")
        if evidence.fitness.memory_mb < baseline_fitness.memory_mb:
            lessons.append("retain strategy: memory use improved")
        lessons.append("re-evaluate inherited candidate under the next frozen suite before selection")

        canonical = {
            "source_generation": source_generation,
            "proposed_generation": proposed_generation,
            "candidate": plan.candidate_id,
            "parents": list(zip(plan.parent_model_ids, plan.parent_artifact_digests)),
            "artifact": outcome.output_artifact_digest,
            "suite": expected_suite_digest,
            "recipe": plan.recipe_digest,
            "strategy": plan.strategy,
            "fitness": {
                "accuracy": evidence.fitness.accuracy,
                "instruction_following": evidence.fitness.instruction_following,
                "safety": evidence.fitness.safety,
                "latency_ms": evidence.fitness.latency_ms,
                "memory_mb": evidence.fitness.memory_mb,
                "regression_count": evidence.fitness.regression_count,
            },
            "outcome": outcome.outcome_digest,
            "evidence": evidence.evidence_digest,
            "evaluator": evidence.evaluator_id,
            "lessons": lessons,
        }
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        record = GenerationKnowledge(
            transfer_id=hashlib.sha256(("transfer:" + digest).encode()).hexdigest(),
            source_generation=source_generation,
            proposed_generation=proposed_generation,
            source_candidate_id=plan.candidate_id,
            parent_model_ids=plan.parent_model_ids,
            parent_artifact_digests=plan.parent_artifact_digests,
            candidate_artifact_digest=outcome.output_artifact_digest,
            evaluation_suite_digest=expected_suite_digest,
            recipe_digest=plan.recipe_digest,
            strategy=plan.strategy,
            fitness=evidence.fitness,
            outcome_digest=outcome.outcome_digest,
            evidence_digest=evidence.evidence_digest,
            evaluator_id=evidence.evaluator_id,
            lessons=tuple(lessons),
            record_digest=digest,
        )
        self._records.append(record)
        self._outcomes.add(outcome.outcome_digest)
        self._suite_by_generation[source_generation] = expected_suite_digest
        return record

    def snapshot(self) -> KnowledgeTransferSnapshot:
        payload = [x.record_digest for x in self._records]
        digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        return KnowledgeTransferSnapshot(
            records=tuple(self._records),
            source_generations=tuple(x.source_generation for x in self._records),
            proposed_generations=tuple(x.proposed_generation for x in self._records),
            digest=digest,
        )


__all__ = [
    "KnowledgeTransferError", "Stage156SignedEvidence", "GenerationKnowledge",
    "KnowledgeTransferSnapshot", "AuthenticatedKnowledgeTransfer",
]
