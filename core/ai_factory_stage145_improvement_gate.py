"""Stage 145: authenticated generation-over-generation improvement gate.

Requires independently signed evidence for every parent and the child, binds
all measurements to the same evaluation-suite digest, and only admits a child
when it dominates at least one parent without violating cross-parent guardrails.
This is metadata/evidence selection only; it never merges or activates weights.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping, Sequence

from .ai_factory_stage141_evolution import Fitness, ModelCandidate, ModelDescriptor, dominates
from .ai_factory_stage142_lineage import EvaluationEvidence, ModelLineageRecord
from .ai_factory_stage143_evidence_auth import AuthenticatedEvidenceVerifier
from .ai_factory_stage144_evolution_selection import AuthenticatedEvolutionEvidenceStore


class EvolutionDecision(str, Enum):
    IMPROVED = "improved"
    NO_IMPROVEMENT = "no_improvement"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SignedEvidence:
    evidence: EvaluationEvidence
    key_id: str
    nonce: str
    signature_hex: str


@dataclass(frozen=True)
class ParentEvaluation:
    descriptor: ModelDescriptor
    generation: int
    signed_evidence: SignedEvidence


@dataclass(frozen=True)
class ParentComparison:
    parent_id: str
    parent_generation: int
    dominates_parent: bool
    accuracy_delta: float
    instruction_following_delta: float
    safety_delta: float
    latency_ratio: float
    memory_ratio: float
    regression_delta: int


@dataclass(frozen=True)
class GenerationImprovementReport:
    candidate_id: str
    generation: int
    decision: EvolutionDecision
    comparisons: tuple[ParentComparison, ...]
    lineage_record: ModelLineageRecord | None
    reason: str


class GenerationImprovementGate:
    """Verifies parent baselines, checks hard guardrails, then admits a child."""

    def __init__(
        self,
        verifier: AuthenticatedEvidenceVerifier,
        selection_store: AuthenticatedEvolutionEvidenceStore,
        *,
        max_parents: int = 4,
        max_accuracy_regression: float = 0.01,
        max_instruction_regression: float = 0.01,
        max_safety_regression: float = 0.005,
        max_resource_ratio: float = 1.10,
    ) -> None:
        if not isinstance(verifier, AuthenticatedEvidenceVerifier):
            raise TypeError("Stage 143 authenticated verifier is required")
        if not isinstance(selection_store, AuthenticatedEvolutionEvidenceStore):
            raise TypeError("Stage 144 authenticated selection store is required")
        if not isinstance(max_parents, int) or isinstance(max_parents, bool) or not 2 <= max_parents <= 4:
            raise ValueError("max_parents must be between 2 and 4")
        for name, value in (
            ("max_accuracy_regression", max_accuracy_regression),
            ("max_instruction_regression", max_instruction_regression),
            ("max_safety_regression", max_safety_regression),
        ):
            if not isinstance(value, (int, float)) or not 0 <= value <= 0.1:
                raise ValueError(f"{name} must be between 0 and 0.1")
        if not isinstance(max_resource_ratio, (int, float)) or not 1.0 <= max_resource_ratio <= 2.0:
            raise ValueError("max_resource_ratio must be between 1.0 and 2.0")
        self._verifier = verifier
        self._store = selection_store
        self._max_parents = max_parents
        self._max_accuracy_regression = max_accuracy_regression
        self._max_instruction_regression = max_instruction_regression
        self._max_safety_regression = max_safety_regression
        self._max_resource_ratio = max_resource_ratio

    @staticmethod
    def _verify(
        verifier: AuthenticatedEvidenceVerifier,
        signed: SignedEvidence,
        *,
        expected_id: str,
        expected_artifact: str,
        expected_suite: str,
    ) -> Fitness:
        verified = verifier.verify(
            signed.evidence,
            key_id=signed.key_id,
            nonce=signed.nonce,
            signature_hex=signed.signature_hex,
            expected_candidate_id=expected_id,
            expected_artifact_digest=expected_artifact,
            expected_suite_digest=expected_suite,
        )
        return verified.fitness

    def evaluate(
        self,
        candidate: ModelCandidate,
        parents: Sequence[ParentEvaluation],
        candidate_evidence: SignedEvidence,
        *,
        expected_candidate_artifact_digest: str,
    ) -> GenerationImprovementReport:
        def blocked(reason: str, comparisons: tuple[ParentComparison, ...] = ()) -> GenerationImprovementReport:
            return GenerationImprovementReport(
                candidate.candidate_id if isinstance(candidate, ModelCandidate) else "",
                candidate.generation if isinstance(candidate, ModelCandidate) else 0,
                EvolutionDecision.BLOCKED, comparisons, None, reason,
            )

        if not isinstance(candidate, ModelCandidate):
            return blocked("typed Stage 141 candidate is required")
        if candidate.enabled or candidate.status.value != "pending_human_approval":
            return blocked("candidate must remain disabled and pending human approval")
        if not isinstance(parents, Sequence) or not 2 <= len(parents) <= self._max_parents:
            return blocked("2-4 authenticated parent evaluations are required")
        if tuple(item.descriptor.model_id for item in parents) != candidate.parent_ids:
            return blocked("parent descriptors do not match candidate parent IDs")
        if len({item.descriptor.model_id for item in parents}) != len(parents):
            return blocked("parent IDs must be unique")
        if any(not isinstance(item.generation, int) or isinstance(item.generation, bool) or item.generation < 0
               for item in parents):
            return blocked("parent generations must be non-negative integers")
        expected_generation = max(item.generation for item in parents) + 1
        if candidate.generation != expected_generation:
            return blocked("candidate generation must be exactly one above the newest parent")
        suite = candidate.fitness.evaluation_suite_digest
        if not isinstance(expected_candidate_artifact_digest, str) or len(expected_candidate_artifact_digest) != 64:
            return blocked("candidate artifact digest is missing or malformed")

        parent_fitness: list[tuple[ParentEvaluation, Fitness]] = []
        try:
            for item in parents:
                if not isinstance(item, ParentEvaluation):
                    return blocked("parent evaluation record has an invalid type")
                fitness = self._verify(
                    self._verifier,
                    item.signed_evidence,
                    expected_id=item.descriptor.model_id,
                    expected_artifact=item.descriptor.artifact_digest,
                    expected_suite=suite,
                )
                parent_fitness.append((item, fitness))
        except (PermissionError, TypeError, ValueError) as exc:
            return blocked(f"parent evidence rejected: {exc}")

        comparisons = tuple(
            ParentComparison(
                parent_id=item.descriptor.model_id,
                parent_generation=item.generation,
                dominates_parent=dominates(candidate.fitness, fitness),
                accuracy_delta=candidate.fitness.accuracy - fitness.accuracy,
                instruction_following_delta=(
                    candidate.fitness.instruction_following - fitness.instruction_following
                ),
                safety_delta=candidate.fitness.safety - fitness.safety,
                latency_ratio=candidate.fitness.latency_ms / fitness.latency_ms,
                memory_ratio=candidate.fitness.memory_mb / fitness.memory_mb,
                regression_delta=candidate.fitness.regression_count - fitness.regression_count,
            )
            for item, fitness in parent_fitness
        )

        if candidate.fitness.safety < 0.95 or candidate.fitness.regression_count != 0:
            return GenerationImprovementReport(
                candidate.candidate_id, candidate.generation, EvolutionDecision.BLOCKED,
                comparisons, None, "child failed absolute safety or regression gate",
            )
        for comparison in comparisons:
            # Treat binary floating-point noise at the exact configured boundary as equal.
            if (comparison.accuracy_delta < -self._max_accuracy_regression
                    and not math.isclose(comparison.accuracy_delta, -self._max_accuracy_regression,
                                         rel_tol=0.0, abs_tol=1e-12)):
                return GenerationImprovementReport(candidate.candidate_id, candidate.generation,
                    EvolutionDecision.BLOCKED, comparisons, None,
                    f"accuracy regression exceeded guardrail against {comparison.parent_id}")
            if (comparison.instruction_following_delta < -self._max_instruction_regression
                    and not math.isclose(comparison.instruction_following_delta, -self._max_instruction_regression,
                                         rel_tol=0.0, abs_tol=1e-12)):
                return GenerationImprovementReport(candidate.candidate_id, candidate.generation,
                    EvolutionDecision.BLOCKED, comparisons, None,
                    f"instruction-following regression exceeded guardrail against {comparison.parent_id}")
            if (comparison.safety_delta < -self._max_safety_regression
                    and not math.isclose(comparison.safety_delta, -self._max_safety_regression,
                                         rel_tol=0.0, abs_tol=1e-12)):
                return GenerationImprovementReport(candidate.candidate_id, candidate.generation,
                    EvolutionDecision.BLOCKED, comparisons, None,
                    f"safety regression exceeded guardrail against {comparison.parent_id}")
            if comparison.latency_ratio > self._max_resource_ratio or comparison.memory_ratio > self._max_resource_ratio:
                return GenerationImprovementReport(candidate.candidate_id, candidate.generation,
                    EvolutionDecision.BLOCKED, comparisons, None,
                    f"resource regression exceeded guardrail against {comparison.parent_id}")

        if not any(item.dominates_parent for item in comparisons):
            return GenerationImprovementReport(candidate.candidate_id, candidate.generation,
                EvolutionDecision.NO_IMPROVEMENT, comparisons, None,
                "child does not Pareto-dominate any authenticated parent")

        try:
            record = self._store.accept(
                candidate,
                tuple(item.descriptor for item in parents),
                candidate_evidence.evidence,
                key_id=candidate_evidence.key_id,
                nonce=candidate_evidence.nonce,
                signature_hex=candidate_evidence.signature_hex,
                expected_artifact_digest=expected_candidate_artifact_digest,
                expected_suite_digest=suite,
                parent_generations={item.descriptor.model_id: item.generation for item in parents},
            )
        except (PermissionError, TypeError, ValueError, OverflowError) as exc:
            return blocked(f"candidate evidence or lineage rejected: {exc}", comparisons)

        return GenerationImprovementReport(
            candidate.candidate_id, candidate.generation, EvolutionDecision.IMPROVED,
            comparisons, record,
            "authenticated child dominates at least one parent and passes all guardrails; human approval still required",
        )


__all__ = [
    "EvolutionDecision", "SignedEvidence", "ParentEvaluation", "ParentComparison",
    "GenerationImprovementReport", "GenerationImprovementGate",
]
