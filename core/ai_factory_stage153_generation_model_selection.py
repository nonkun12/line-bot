"""Stage 153: evidence-bound cross-generation model selection proposals.

Consumes the authenticated, immutable Stage 149 population snapshot. It compares
candidates only under one frozen evaluation suite and emits bounded survivor and
merge-strategy proposals. It never merges weights or advances/activates a generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Sequence

from .ai_factory_stage141_evolution import (
    CandidateStatus, Fitness, MergeStrategy, ModelDescriptor,
    assess_compatibility, dominates,
)
from .ai_factory_stage149_evolutionary_selection import (
    EvolutionPopulationEntry, EvolutionPopulationSnapshot,
)


_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class GenerationSelectionError(ValueError):
    """Raised when a population cannot be safely compared."""


class SelectionDecision(str, Enum):
    SELECTED = "selected"
    FRONTIER_ONLY = "frontier_only"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CandidateModelEvidence:
    entry: EvolutionPopulationEntry
    parent_descriptors: tuple[ModelDescriptor, ...]


@dataclass(frozen=True)
class CandidateSelection:
    candidate_id: str
    generation: int
    decision: SelectionDecision
    pareto_frontier: bool
    rank: int | None
    merge_strategy: MergeStrategy
    compatibility_reasons: tuple[str, ...]
    artifact_digest: str
    evidence_digest: str
    execution_authorized: bool = False
    merge_authorized: bool = False
    activation_authorized: bool = False


@dataclass(frozen=True)
class GenerationSelectionReport:
    evaluation_suite_digest: str
    observed_generations: tuple[int, ...]
    selections: tuple[CandidateSelection, ...]
    survivor_candidate_ids: tuple[str, ...]
    next_generation: int
    digest: str
    proposal_only: bool = True
    auto_advance: bool = False
    production_switch_authorized: bool = False


def _fitness_order(item: CandidateModelEvidence) -> tuple[float, float, float, float, float, int, str]:
    f = item.entry.fitness
    return (-f.safety, -f.accuracy, -f.instruction_following,
            f.latency_ms, f.memory_mb, f.regression_count, item.entry.candidate_id)


class EvolutionaryGenerationSelector:
    """Deterministic Pareto/diversity selector over independently admitted candidates."""

    def __init__(self, *, max_candidates: int = 128, max_survivors: int = 16,
                 minimum_safety: float = 0.95) -> None:
        if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or not 1 <= max_candidates <= 512:
            raise ValueError("max_candidates must be between 1 and 512")
        if not isinstance(max_survivors, int) or isinstance(max_survivors, bool) or not 1 <= max_survivors <= max_candidates:
            raise ValueError("max_survivors must be between 1 and max_candidates")
        if not isinstance(minimum_safety, (int, float)) or not 0.95 <= minimum_safety <= 1:
            raise ValueError("minimum_safety must be between 0.95 and 1")
        self._max_candidates = max_candidates
        self._max_survivors = max_survivors
        self._minimum_safety = float(minimum_safety)

    def select(
        self,
        population: EvolutionPopulationSnapshot,
        candidates: Sequence[CandidateModelEvidence],
        *,
        expected_suite_digest: str,
        kill_switch_active: bool = False,
        hold_active: bool = False,
        budget_available: bool = True,
        max_generation: int = 1_000_000,
    ) -> GenerationSelectionReport:
        if kill_switch_active or hold_active or not budget_available:
            raise GenerationSelectionError("kill switch, HOLD, or unavailable budget blocks selection")
        if not isinstance(population, EvolutionPopulationSnapshot):
            raise GenerationSelectionError("authenticated Stage 149 population snapshot is required")
        if not isinstance(candidates, Sequence) or not candidates or len(candidates) > self._max_candidates:
            raise GenerationSelectionError("candidate set is empty or exceeds the configured bound")
        if not _HEX.fullmatch(expected_suite_digest or ""):
            raise GenerationSelectionError("expected evaluation suite must be a SHA-256 digest")
        if not isinstance(max_generation, int) or isinstance(max_generation, bool) or max_generation < 1:
            raise GenerationSelectionError("max_generation must be a positive integer")
        if population.capacity < len(population.entries) or len(population.entries) > self._max_candidates:
            raise GenerationSelectionError("population capacity metadata is inconsistent or exceeds bounds")

        entries = {x.candidate_id: x for x in population.entries}
        if len(entries) != len(population.entries):
            raise GenerationSelectionError("duplicate candidate IDs in population snapshot")
        supplied: dict[str, CandidateModelEvidence] = {}
        for item in candidates:
            if not isinstance(item, CandidateModelEvidence) or not isinstance(item.entry, EvolutionPopulationEntry):
                raise GenerationSelectionError("typed candidate model evidence is required")
            entry = item.entry
            admitted = entries.get(entry.candidate_id)
            if admitted != entry:
                raise GenerationSelectionError("candidate is not the exact immutable Stage 149 population entry")
            if entry.candidate_id in supplied:
                raise GenerationSelectionError("duplicate candidate supplied")
            if entry.enabled or entry.status != "pending_human_approval":
                raise GenerationSelectionError("enabled or non-pending candidate is ineligible")
            if entry.evaluation_suite_digest != expected_suite_digest or entry.fitness.evaluation_suite_digest != expected_suite_digest:
                raise GenerationSelectionError("candidate evaluation suite differs from frozen suite")
            if not _HEX.fullmatch(entry.artifact_digest or "") or not _HEX.fullmatch(entry.evidence_digest or ""):
                raise GenerationSelectionError("candidate artifact/evidence digest is invalid")
            if not 1 <= entry.generation <= max_generation or not _ID.fullmatch(entry.candidate_id or ""):
                raise GenerationSelectionError("candidate identity or generation is outside bounds")
            if not isinstance(item.parent_descriptors, tuple) or len(item.parent_descriptors) != len(entry.parent_ids):
                raise GenerationSelectionError("one immutable parent descriptor per lineage parent is required")
            if tuple(x.model_id for x in item.parent_descriptors) != entry.parent_ids:
                raise GenerationSelectionError("parent descriptor identity/order differs from candidate lineage")
            if len(set(entry.parent_ids)) != len(entry.parent_ids):
                raise GenerationSelectionError("duplicate parent IDs are not allowed")
            if any(not isinstance(x, ModelDescriptor) for x in item.parent_descriptors):
                raise GenerationSelectionError("typed parent model descriptors are required")
            supplied[entry.candidate_id] = item

        # A supplied subset must not silently omit any entry from the selected generations.
        if set(supplied) != set(entries):
            raise GenerationSelectionError("every admitted population entry must be represented exactly once")
        generations = tuple(sorted({x.entry.generation for x in supplied.values()}))
        if not generations or generations != population.generation_numbers:
            raise GenerationSelectionError("generation index does not match exact population contents")
        if any(x.entry.fitness.safety < self._minimum_safety or x.entry.fitness.regression_count != 0
               for x in supplied.values()):
            raise GenerationSelectionError("absolute safety or regression gate failed")
        if max(generations) >= max_generation:
            raise GenerationSelectionError("maximum generation reached; selection is fail-closed")

        # Frontier is calculated independently from the population's cached value.
        ordered = tuple(supplied[key] for key in sorted(supplied))
        frontier = {
            item.entry.candidate_id for item in ordered
            if not any(other.entry.candidate_id != item.entry.candidate_id
                       and dominates(other.entry.fitness, item.entry.fitness)
                       for other in ordered)
        }
        if tuple(sorted(frontier)) != tuple(sorted(population.pareto_frontier)):
            raise GenerationSelectionError("cached Pareto frontier differs from independently recomputed frontier")

        # Prefer one candidate per distinct parent set, then fill by stable multi-objective tie-break.
        ranked = sorted(ordered, key=_fitness_order)
        survivors: list[CandidateModelEvidence] = []
        seen_parent_sets: set[tuple[str, ...]] = set()
        for item in sorted((x for x in ranked if x.entry.candidate_id in frontier), key=_fitness_order):
            key = tuple(sorted(item.entry.parent_ids))
            if key not in seen_parent_sets and len(survivors) < self._max_survivors:
                survivors.append(item)
                seen_parent_sets.add(key)
        for item in ranked:
            if len(survivors) >= self._max_survivors:
                break
            if item.entry.candidate_id not in {x.entry.candidate_id for x in survivors}:
                survivors.append(item)
        survivor_ids = tuple(x.entry.candidate_id for x in survivors)
        rank_by_id = {item.entry.candidate_id: index + 1 for index, item in enumerate(ranked)}
        survivor_set = set(survivor_ids)
        selections = []
        for item in ranked:
            compatibility = assess_compatibility(item.parent_descriptors)
            is_frontier = item.entry.candidate_id in frontier
            decision = (SelectionDecision.SELECTED if item.entry.candidate_id in survivor_set
                        else SelectionDecision.FRONTIER_ONLY if is_frontier
                        else SelectionDecision.REJECTED)
            # Incompatible parents are explicitly routed to orchestration; no tensors are combined.
            selections.append(CandidateSelection(
                item.entry.candidate_id, item.entry.generation, decision, is_frontier,
                rank_by_id[item.entry.candidate_id], compatibility.strategy,
                compatibility.reasons, item.entry.artifact_digest, item.entry.evidence_digest,
            ))
        payload = {
            "suite": expected_suite_digest, "generations": generations,
            "selections": [(x.candidate_id, x.decision.value, x.rank, x.merge_strategy.value,
                            x.artifact_digest, x.evidence_digest) for x in selections],
            "survivors": survivor_ids, "next_generation": max(generations) + 1,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return GenerationSelectionReport(
            expected_suite_digest, generations, tuple(selections), survivor_ids,
            max(generations) + 1, digest,
        )


__all__ = [
    "GenerationSelectionError", "SelectionDecision", "CandidateModelEvidence",
    "CandidateSelection", "GenerationSelectionReport", "EvolutionaryGenerationSelector",
]
