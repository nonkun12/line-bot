"""Stage 167: diversity-preserving evolutionary candidate population proposals.

Builds a bounded, strategy-diverse next-generation cohort from Stage 166's
verified recursive policy revision. It preserves Pareto/repeatability/safety
eligibility and never executes, merges, mutates, advances, or activates models.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

from .ai_factory_stage166_recursive_policy_revision import (
    RecursivePolicyRevisionReport,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ALLOWED = {"slerp", "ties", "dare", "task_arithmetic", "lora",
            "parameter_merge", "multi_model_orchestration"}


class EvolutionaryPopulationDiversityError(ValueError):
    """Raised when the Stage 166 proposal cannot form a trustworthy cohort."""


@dataclass(frozen=True)
class CohortCandidate:
    candidate_id: str
    strategy: str
    revised_prior: float
    evidence_score_digest: str
    strategy_rank: int
    cohort_rank: int


@dataclass(frozen=True)
class StrategyDiversity:
    strategy: str
    available: int
    included: int
    deferred: int
    best_prior: float


@dataclass(frozen=True)
class EvolutionaryPopulationCohort:
    source_revision_digest: str
    evaluation_suite_digest: str
    source_generation: int
    proposed_generation: int
    candidates: tuple[CohortCandidate, ...]
    deferred_candidate_ids: tuple[str, ...]
    strategy_diversity: tuple[StrategyDiversity, ...]
    available_strategy_count: int
    represented_strategy_count: int
    diversity_ratio: float
    digest: str
    proposal_only: bool = True
    candidate_selection_authorized: bool = False
    experiment_execution_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _revision_digest(report: RecursivePolicyRevisionReport) -> str:
    payload = {
        "policy": report.source_policy_digest,
        "feedback": report.feedback_snapshot_digest,
        "tournament": report.tournament_digest,
        "suite": report.evaluation_suite_digest,
        "source_generation": report.source_generation,
        "revisions": [{
            "strategy": x.strategy, "previous": x.previous_prior,
            "revised": x.revised_prior, "observations": x.observations,
            "improved": x.improved, "regressed": x.regressed,
            "safety_failures": x.safety_failures, "stagnant": x.stagnant,
            "confidence": x.confidence, "retention": x.candidate_retention_eligible,
        } for x in report.revised_priors],
        "candidates": [{
            "candidate": x.candidate_id, "strategy": x.strategy,
            "prior": x.revised_prior, "score": x.evidence_score_digest,
        } for x in report.next_generation_candidates],
        "guidance": list(report.exploration_guidance),
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


class EvolutionaryPopulationDiversifier:
    """Creates a bounded, repeatable cohort without collapsing to one strategy."""

    def build(
        self,
        revision: RecursivePolicyRevisionReport,
        *,
        max_cohort_size: int = 16,
        max_per_strategy: int = 4,
        minimum_strategy_coverage: int = 2,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionaryPopulationCohort:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionaryPopulationDiversityError(
                "HOLD, kill switch, or unavailable budget blocks cohort construction"
            )
        if not isinstance(revision, RecursivePolicyRevisionReport):
            raise EvolutionaryPopulationDiversityError("typed Stage 166 revision report is required")
        if (revision.proposal_only is not True or revision.candidate_selection_authorized
                or revision.experiment_execution_authorized or revision.model_mutation_authorized
                or revision.generation_advanced or revision.model_activated
                or revision.production_switch_authorized):
            raise EvolutionaryPopulationDiversityError("Stage 166 report contains forbidden authority")
        if (not all(_valid_digest(x) for x in (
                revision.source_policy_digest, revision.feedback_snapshot_digest,
                revision.tournament_digest, revision.evaluation_suite_digest, revision.digest))):
            raise EvolutionaryPopulationDiversityError("Stage 166 source or report digest is invalid")
        if revision.proposed_generation != revision.source_generation + 1 or revision.source_generation < 0:
            raise EvolutionaryPopulationDiversityError("Stage 166 generation lineage is not adjacent")
        if _revision_digest(revision) != revision.digest:
            raise EvolutionaryPopulationDiversityError("Stage 166 report digest does not match its contents")
        if not isinstance(max_cohort_size, int) or isinstance(max_cohort_size, bool) or not 1 <= max_cohort_size <= 64:
            raise EvolutionaryPopulationDiversityError("max_cohort_size must be between 1 and 64")
        if not isinstance(max_per_strategy, int) or isinstance(max_per_strategy, bool) or not 1 <= max_per_strategy <= max_cohort_size:
            raise EvolutionaryPopulationDiversityError("max_per_strategy must be between 1 and max_cohort_size")
        if (not isinstance(minimum_strategy_coverage, int) or isinstance(minimum_strategy_coverage, bool)
                or not 1 <= minimum_strategy_coverage <= max_cohort_size):
            raise EvolutionaryPopulationDiversityError("minimum_strategy_coverage must be between 1 and max_cohort_size")
        if len(revision.next_generation_candidates) > 4096 or len(revision.revised_priors) > 64:
            raise EvolutionaryPopulationDiversityError("Stage 166 input exceeds cohort capacity")

        eligible_prior = {}
        for item in revision.revised_priors:
            if item.strategy not in _ALLOWED or item.strategy in eligible_prior:
                raise EvolutionaryPopulationDiversityError("duplicate or unknown revised strategy")
            numbers = (item.previous_prior, item.revised_prior, item.confidence)
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in numbers):
                raise EvolutionaryPopulationDiversityError("revised prior values must be finite")
            if abs(item.revised_prior) > 0.15 or not 0 <= item.confidence <= 1:
                raise EvolutionaryPopulationDiversityError("revised prior or confidence exceeds Stage 162 bounds")
            eligible_prior[item.strategy] = item

        by_strategy = {}
        seen_ids, seen_evidence = set(), set()
        for item in revision.next_generation_candidates:
            if (not item.candidate_id or len(item.candidate_id) > 128
                    or item.strategy not in _ALLOWED
                    or not _valid_digest(item.evidence_score_digest)
                    or not isinstance(item.revised_prior, (int, float))
                    or isinstance(item.revised_prior, bool) or not math.isfinite(item.revised_prior)):
                raise EvolutionaryPopulationDiversityError("candidate identity, strategy, prior, or evidence is invalid")
            if item.candidate_id in seen_ids or item.evidence_score_digest in seen_evidence:
                raise EvolutionaryPopulationDiversityError("duplicate candidate or replayed score evidence")
            if item.pareto_eligible is not True or item.repeatable is not True:
                raise EvolutionaryPopulationDiversityError("non-Pareto or non-repeatable candidate cannot enter cohort")
            prior = eligible_prior.get(item.strategy)
            if prior is not None and not prior.candidate_retention_eligible:
                raise EvolutionaryPopulationDiversityError("candidate strategy failed Stage 166 retention gate")
            if prior is not None and abs(item.revised_prior - prior.revised_prior) > 1e-12:
                raise EvolutionaryPopulationDiversityError("candidate prior differs from Stage 166 strategy revision")
            seen_ids.add(item.candidate_id)
            seen_evidence.add(item.evidence_score_digest)
            by_strategy.setdefault(item.strategy, []).append(item)

        strategies = sorted(by_strategy)
        if len(strategies) > 64:
            raise EvolutionaryPopulationDiversityError("strategy count exceeds capacity")
        # Within each strategy, prefer the strongest revised prior, then stable evidence identity.
        for strategy in strategies:
            by_strategy[strategy].sort(
                key=lambda x: (-x.revised_prior, x.candidate_id, x.evidence_score_digest)
            )

        # First pass guarantees breadth: at most one candidate per strategy before
        # any strategy receives a second slot. Remaining slots are filled by prior.
        selected = []
        selected_ids = set()
        first_pass = sorted(
            ((items[0].revised_prior, strategy, items[0]) for strategy, items in by_strategy.items()),
            key=lambda row: (-row[0], row[1], row[2].candidate_id),
        )
        target_coverage = min(minimum_strategy_coverage, len(strategies), max_cohort_size)
        for _, strategy, item in first_pass:
            if len(selected) >= target_coverage:
                break
            selected.append((strategy, item))
            selected_ids.add(item.candidate_id)

        counts = {strategy: 0 for strategy in strategies}
        for strategy, _ in selected:
            counts[strategy] += 1

        remaining = sorted(
            ((item.revised_prior, strategy, item)
             for strategy, items in by_strategy.items() for item in items
             if item.candidate_id not in selected_ids),
            key=lambda row: (-row[0], row[1], row[2].candidate_id),
        )
        for _, strategy, item in remaining:
            if len(selected) >= max_cohort_size:
                break
            if counts[strategy] >= max_per_strategy:
                continue
            selected.append((strategy, item))
            selected_ids.add(item.candidate_id)
            counts[strategy] += 1

        # Strategy-local rank and cohort rank are stable and digest-bound.
        local_rank = {}
        for strategy, items in by_strategy.items():
            local_rank.update({item.candidate_id: i + 1 for i, item in enumerate(items)})
        cohort = tuple(
            CohortCandidate(item.candidate_id, strategy, item.revised_prior,
                            item.evidence_score_digest, local_rank[item.candidate_id], index + 1)
            for index, (strategy, item) in enumerate(selected)
        )
        deferred = tuple(sorted(seen_ids - selected_ids))
        diversity = tuple(
            StrategyDiversity(strategy, len(by_strategy[strategy]), counts[strategy],
                              len(by_strategy[strategy]) - counts[strategy],
                              by_strategy[strategy][0].revised_prior)
            for strategy in strategies
        )
        represented = sum(1 for x in diversity if x.included)
        ratio = represented / len(strategies) if strategies else 0.0
        payload = {
            "source_revision": revision.digest,
            "suite": revision.evaluation_suite_digest,
            "source_generation": revision.source_generation,
            "proposed_generation": revision.proposed_generation,
            "candidates": [(x.candidate_id, x.strategy, x.revised_prior,
                            x.evidence_score_digest, x.strategy_rank, x.cohort_rank) for x in cohort],
            "deferred": deferred,
            "diversity": [(x.strategy, x.available, x.included, x.deferred, x.best_prior) for x in diversity],
            "available_strategy_count": len(strategies),
            "represented_strategy_count": represented,
            "diversity_ratio": ratio,
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return EvolutionaryPopulationCohort(
            revision.digest, revision.evaluation_suite_digest,
            revision.source_generation, revision.proposed_generation,
            cohort, deferred, diversity, len(strategies), represented, ratio, digest,
        )


__all__ = [
    "EvolutionaryPopulationDiversityError", "CohortCandidate",
    "StrategyDiversity", "EvolutionaryPopulationCohort",
    "EvolutionaryPopulationDiversifier",
]
