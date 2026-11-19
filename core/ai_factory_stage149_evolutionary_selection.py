"""Stage 149: authenticated evolutionary population and generation selection.

Only independently signed evaluation evidence can enter the bounded population.
Selection is deterministic and proposal-only: it never runs inference, merges
weights, advances a generation, activates a model, or changes production state.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Sequence

from .ai_factory_stage141_evolution import Fitness, ModelCandidate, dominates
from .ai_factory_stage142_lineage import ModelLineageRecord
from .ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier,
    EvidenceVerificationError,
)
from .ai_factory_stage145_improvement_gate import (
    EvolutionDecision,
    GenerationImprovementReport,
    ParentEvaluation,
    SignedEvidence,
)
from .ai_factory_stage146_merge_strategy import MergeRecipe, MergeReadiness


class EvolutionPopulationError(ValueError):
    """Raised when a candidate cannot safely enter the evolutionary population."""


@dataclass(frozen=True)
class EvolutionPopulationEntry:
    candidate_id: str
    generation: int
    parent_ids: tuple[str, ...]
    artifact_digest: str
    evidence_digest: str
    evaluation_suite_digest: str
    fitness: Fitness
    status: str = "pending_human_approval"
    enabled: bool = False


@dataclass(frozen=True)
class EvolutionPopulationSnapshot:
    entries: tuple[EvolutionPopulationEntry, ...]
    pareto_frontier: tuple[str, ...]
    generation_numbers: tuple[int, ...]
    capacity: int


@dataclass(frozen=True)
class EvolutionGenerationPlan:
    source_generation: int
    next_generation: int
    frontier_candidate_ids: tuple[str, ...]
    survivor_candidate_ids: tuple[str, ...]
    parent_references: tuple[tuple[str, tuple[str, ...]], ...]
    deterministic_order: tuple[str, ...]
    auto_advance: bool = False
    merge_authorized: bool = False
    activation_authorized: bool = False
    production_switch_authorized: bool = False
    reason: str = "proposal only; human approval is required before any subsequent operation"


def _fitness_order(item: EvolutionPopulationEntry) -> tuple[float, float, float, float, float, int, str]:
    """Stable tie-break: quality/safety first, then lower resource use and ID."""
    f = item.fitness
    return (-f.safety, -f.accuracy, -f.instruction_following,
            f.latency_ms, f.memory_mb, f.regression_count, item.candidate_id)


def _frontier(entries: Sequence[EvolutionPopulationEntry]) -> tuple[str, ...]:
    eligible = tuple(
        item for item in entries
        if item.status == "pending_human_approval" and not item.enabled
        and item.fitness.safety >= 0.95 and item.fitness.regression_count == 0
    )
    result = [
        item.candidate_id for item in eligible
        if not any(
            other.candidate_id != item.candidate_id
            and dominates(other.fitness, item.fitness)
            for other in eligible
        )
    ]
    return tuple(sorted(result))


class EvolutionaryPopulation:
    """Bounded, append-only candidate pool with independent evidence verification."""

    def __init__(
        self,
        verifier: AuthenticatedEvidenceVerifier,
        *,
        max_population: int = 64,
        max_generation: int = 10_000,
        max_survivors: int = 16,
    ) -> None:
        if not isinstance(verifier, AuthenticatedEvidenceVerifier):
            raise TypeError("an independent Stage 143 evidence verifier is required")
        if not isinstance(max_population, int) or isinstance(max_population, bool) or not 1 <= max_population <= 128:
            raise ValueError("max_population must be between 1 and 128")
        if not isinstance(max_generation, int) or isinstance(max_generation, bool) or not 1 <= max_generation <= 1_000_000:
            raise ValueError("max_generation must be between 1 and 1000000")
        if not isinstance(max_survivors, int) or isinstance(max_survivors, bool) or not 1 <= max_survivors <= max_population:
            raise ValueError("max_survivors must be between 1 and max_population")
        self._verifier = verifier
        self._max_population = max_population
        self._max_generation = max_generation
        self._max_survivors = max_survivors
        self._entries: dict[str, EvolutionPopulationEntry] = {}
        self._artifact_index: dict[str, str] = {}
        self._lock = RLock()

    def admit(
        self,
        candidate: ModelCandidate,
        report: GenerationImprovementReport,
        recipe: MergeRecipe,
        signed_evidence: SignedEvidence,
        parent_evaluations: Sequence[ParentEvaluation],
        *,
        expected_artifact_digest: str,
        kill_switch_active: bool = False,
        hold_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionPopulationEntry:
        """Re-verify signed child evidence before immutable population admission."""
        if kill_switch_active or hold_active or not budget_available:
            raise EvolutionPopulationError("kill switch, HOLD, or unavailable budget blocks admission")
        if not isinstance(candidate, ModelCandidate):
            raise EvolutionPopulationError("typed Stage 141 candidate is required")
        if not isinstance(report, GenerationImprovementReport) or report.decision is not EvolutionDecision.IMPROVED:
            raise EvolutionPopulationError("an IMPROVED Stage 145 report is required")
        if not isinstance(recipe, MergeRecipe) or recipe.readiness is not MergeReadiness.PROPOSAL_ONLY:
            raise EvolutionPopulationError("a proposal-only Stage 146 recipe is required")
        if not isinstance(signed_evidence, SignedEvidence):
            raise EvolutionPopulationError("signed independent evaluation evidence is required")
        if candidate.enabled or candidate.status.value != "pending_human_approval":
            raise EvolutionPopulationError("candidate must remain disabled and pending human approval")
        if not isinstance(report.lineage_record, ModelLineageRecord):
            raise EvolutionPopulationError("typed authenticated Stage 142 lineage record is required")
        if report.candidate_id != candidate.candidate_id or report.generation != candidate.generation:
            raise EvolutionPopulationError("Stage 145 report identity differs from candidate")
        if recipe.candidate_id != candidate.candidate_id or recipe.generation != candidate.generation:
            raise EvolutionPopulationError("merge recipe identity differs from candidate")
        if recipe.parent_ids != candidate.parent_ids or len(set(candidate.parent_ids)) != len(candidate.parent_ids):
            raise EvolutionPopulationError("recipe parents must exactly match unique candidate parents")
        if not 2 <= len(candidate.parent_ids) <= 4:
            raise EvolutionPopulationError("candidate must have between two and four parents")
        if candidate.generation < 1 or candidate.generation > self._max_generation:
            raise EvolutionPopulationError("candidate generation is outside the configured bound")
        lineage = report.lineage_record
        if (lineage.candidate_id != candidate.candidate_id
                or lineage.parent_ids != candidate.parent_ids
                or lineage.generation != candidate.generation
                or lineage.evaluated_artifact_digest != expected_artifact_digest
                or lineage.evaluation_suite_digest != recipe.evidence_suite_digest
                or lineage.enabled or lineage.status.value != "pending_human_approval"):
            raise EvolutionPopulationError("authenticated lineage does not bind exact candidate, parents, generation and artifact")
        if recipe.output_artifact_digest != expected_artifact_digest:
            raise EvolutionPopulationError("recipe output digest differs from the independently verified artifact digest")
        if recipe.evidence_suite_digest != candidate.fitness.evaluation_suite_digest:
            raise EvolutionPopulationError("recipe and candidate evaluation-suite digests differ")
        if report.candidate_id != signed_evidence.evidence.candidate_id:
            raise EvolutionPopulationError("signed evidence candidate identity mismatch")
        if report.generation != candidate.generation:
            raise EvolutionPopulationError("generation mismatch")
        if signed_evidence.evidence.fitness != candidate.fitness:
            raise EvolutionPopulationError("signed evidence metrics differ from candidate fitness")
        if not isinstance(parent_evaluations, Sequence) or len(parent_evaluations) != len(candidate.parent_ids):
            raise EvolutionPopulationError("one independently signed parent evaluation per parent is required")
        if tuple(item.descriptor.model_id for item in parent_evaluations) != candidate.parent_ids:
            raise EvolutionPopulationError("parent evaluation identities/order differ from candidate lineage")
        if tuple(item.descriptor.artifact_digest for item in parent_evaluations) != lineage.parent_artifact_digests:
            raise EvolutionPopulationError("parent evaluation artifacts differ from authenticated lineage")
        if not report.comparisons or {item.parent_id for item in report.comparisons} != set(candidate.parent_ids):
            raise EvolutionPopulationError("Stage 145 comparison set does not match exact candidate parents")
        if candidate.fitness.safety < 0.95 or candidate.fitness.regression_count != 0:
            raise EvolutionPopulationError("absolute safety or regression guardrail failed")

        try:
            verified = self._verifier.verify(
                signed_evidence.evidence,
                key_id=signed_evidence.key_id,
                nonce=signed_evidence.nonce,
                signature_hex=signed_evidence.signature_hex,
                expected_candidate_id=candidate.candidate_id,
                expected_artifact_digest=expected_artifact_digest,
                expected_suite_digest=recipe.evidence_suite_digest,
            )
        except (EvidenceVerificationError, PermissionError, TypeError, ValueError) as exc:
            raise EvolutionPopulationError(f"independent signature verification failed: {exc}") from exc

        parent_fitnesses = []
        try:
            for parent in parent_evaluations:
                verified_parent = self._verifier.verify(
                    parent.signed_evidence.evidence,
                    key_id=parent.signed_evidence.key_id,
                    nonce=parent.signed_evidence.nonce,
                    signature_hex=parent.signed_evidence.signature_hex,
                    expected_candidate_id=parent.descriptor.model_id,
                    expected_artifact_digest=parent.descriptor.artifact_digest,
                    expected_suite_digest=recipe.evidence_suite_digest,
                )
                if parent.generation < 0 or candidate.generation <= parent.generation:
                    raise EvolutionPopulationError("candidate generation must follow each authenticated parent")
                parent_fitnesses.append(verified_parent.fitness)
        except (EvidenceVerificationError, PermissionError, TypeError, ValueError) as exc:
            raise EvolutionPopulationError(f"independent parent evidence verification failed: {exc}") from exc
        if candidate.generation != max(item.generation for item in parent_evaluations) + 1:
            raise EvolutionPopulationError("candidate generation must be exactly one above newest parent")
        if not any(dominates(verified.fitness, fitness) for fitness in parent_fitnesses):
            raise EvolutionPopulationError("signed child evidence does not Pareto-dominate any signed parent")

        entry = EvolutionPopulationEntry(
            candidate_id=candidate.candidate_id,
            generation=candidate.generation,
            parent_ids=tuple(candidate.parent_ids),
            artifact_digest=expected_artifact_digest,
            evidence_digest=verified.evidence_digest,
            evaluation_suite_digest=verified.evaluation_suite_digest,
            fitness=verified.fitness,
        )
        with self._lock:
            existing = self._entries.get(entry.candidate_id)
            if existing is not None:
                if existing == entry:
                    return existing
                raise EvolutionPopulationError("candidate ID is already bound to different immutable evidence")
            if entry.artifact_digest in self._artifact_index:
                raise EvolutionPopulationError("artifact digest is already assigned to another candidate")
            if len(self._entries) >= self._max_population:
                raise EvolutionPopulationError("population capacity reached; admission is fail-closed")
            self._entries[entry.candidate_id] = entry
            self._artifact_index[entry.artifact_digest] = entry.candidate_id
        return entry

    def snapshot(self) -> EvolutionPopulationSnapshot:
        with self._lock:
            entries = tuple(sorted(self._entries.values(), key=lambda item: (item.generation, item.candidate_id)))
        return EvolutionPopulationSnapshot(
            entries=entries,
            pareto_frontier=_frontier(entries),
            generation_numbers=tuple(sorted({item.generation for item in entries})),
            capacity=self._max_population,
        )

    def plan_next_generation(self) -> EvolutionGenerationPlan:
        """Create a deterministic survivor proposal; never advances or activates it."""
        snapshot = self.snapshot()
        if not snapshot.entries:
            raise EvolutionPopulationError("cannot plan a generation from an empty population")
        frontier_ids = snapshot.pareto_frontier
        by_id = {item.candidate_id: item for item in snapshot.entries}
        frontier = [by_id[item] for item in frontier_ids]
        ordered_frontier = sorted(frontier, key=_fitness_order)

        # Preserve parent-set diversity first, then fill remaining elite slots by stable rank.
        survivors: list[EvolutionPopulationEntry] = []
        seen_parent_sets: set[tuple[str, ...]] = set()
        for item in ordered_frontier:
            parent_set = tuple(sorted(item.parent_ids))
            if parent_set not in seen_parent_sets and len(survivors) < self._max_survivors:
                survivors.append(item)
                seen_parent_sets.add(parent_set)
        for item in sorted(snapshot.entries, key=_fitness_order):
            if len(survivors) >= self._max_survivors:
                break
            if item.candidate_id not in {chosen.candidate_id for chosen in survivors}:
                survivors.append(item)

        source_generation = max(snapshot.generation_numbers)
        if source_generation >= self._max_generation:
            raise EvolutionPopulationError("maximum generation reached; evolution is fail-closed")
        selected = tuple(item.candidate_id for item in survivors)
        return EvolutionGenerationPlan(
            source_generation=source_generation,
            next_generation=source_generation + 1,
            frontier_candidate_ids=frontier_ids,
            survivor_candidate_ids=selected,
            parent_references=tuple((item.candidate_id, item.parent_ids) for item in survivors),
            deterministic_order=tuple(item.candidate_id for item in sorted(survivors, key=_fitness_order)),
        )


__all__ = [
    "EvolutionPopulationError", "EvolutionPopulationEntry",
    "EvolutionPopulationSnapshot", "EvolutionGenerationPlan",
    "EvolutionaryPopulation",
]
