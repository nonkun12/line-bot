"""Stage 170: evidence-weighted evolutionary merge strategy adaptation.

Turns the verified Stage 169 lineage ledger into a bounded strategy portfolio
proposal for the next isolated evaluation cycle. It ranks merge strategies
using historical survival, retirement, and exploration signals while keeping
incompatible/runtime-orchestration paths separate from parameter merging.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

from .ai_factory_stage169_lineage_survival_ledger import (
    EvolutionaryLineageLedger, CandidateHistory, StrategyHistory,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_PARAMETER = {"slerp", "ties", "dare", "task_arithmetic", "lora", "parameter_merge"}
_ORCHESTRATION = {"multi_model_orchestration"}


class MergeStrategyAdaptationError(ValueError):
    """Raised when the lineage ledger cannot safely inform strategy adaptation."""


@dataclass(frozen=True)
class MergeStrategyAllocation:
    strategy: str
    strategy_class: str
    observations: int
    survival_rate: float
    retirement_rate: float
    reexploration_rate: float
    confidence: float
    priority_score: float
    evaluation_share: float
    rationale: str


@dataclass(frozen=True)
class EvolutionaryMergeStrategyPlan:
    source_ledger_digest: str
    evaluation_suite_digest: str
    source_generation: int
    target_generation: int
    allocations: tuple[MergeStrategyAllocation, ...]
    parameter_merge_share: float
    orchestration_share: float
    exploration_share: float
    digest: str
    proposal_only: bool = True
    strategy_selection_authorized: bool = False
    experiment_execution_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _ledger_digest(ledger: EvolutionaryLineageLedger) -> str:
    payload = {
        "suite": ledger.evaluation_suite_digest,
        "first": ledger.first_generation,
        "latest": ledger.latest_generation,
        "generations": list(range(ledger.first_generation, ledger.latest_generation + 1)),
        "candidates": [(x.candidate_id, x.strategy, x.first_seen_generation,
                        x.last_seen_generation, x.survived_generations,
                        x.retirement_proposals, x.reexploration_events, x.last_status)
                       for x in ledger.candidate_history],
        "strategies": [(x.strategy, x.observed_candidates, x.survivors,
                        x.retirement_proposals, x.reexploration_events, x.survival_rate)
                       for x in ledger.strategy_history],
        "improved": ledger.improved_generations,
        "stagnant": ledger.stagnant_generations,
        "regressed": ledger.regressed_generations,
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def _plan_digest(
    source: str, suite: str, generation: int, target: int,
    allocations: tuple[MergeStrategyAllocation, ...],
    parameter_share: float, orchestration_share: float, exploration_share: float,
) -> str:
    payload = {
        "ledger": source, "suite": suite, "generation": generation, "target": target,
        "allocations": [(x.strategy, x.strategy_class, x.observations, x.survival_rate,
                         x.retirement_rate, x.reexploration_rate, x.confidence,
                         x.priority_score, x.evaluation_share, x.rationale) for x in allocations],
        "parameter_share": parameter_share, "orchestration_share": orchestration_share,
        "exploration_share": exploration_share,
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


class EvolutionaryMergeStrategyAdapter:
    """Creates a bounded, evidence-weighted merge-strategy portfolio proposal."""

    def build(
        self,
        ledger: EvolutionaryLineageLedger,
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_strategies: int = 16,
        minimum_observations: int = 2,
        exploration_floor: float = 0.10,
        maximum_strategy_share: float = 0.60,
    ) -> EvolutionaryMergeStrategyPlan:
        if hold_active or kill_switch_active or not budget_available:
            raise MergeStrategyAdaptationError("HOLD, kill switch, or unavailable budget blocks adaptation")
        if not isinstance(ledger, EvolutionaryLineageLedger):
            raise MergeStrategyAdaptationError("typed Stage 169 lineage ledger is required")
        if (ledger.append_only_proposal is not True or ledger.history_rewrite_authorized
                or ledger.survival_selection_authorized or ledger.retirement_executed
                or ledger.model_merge_authorized or ledger.weight_mutation_authorized
                or ledger.generation_advanced or ledger.model_activated
                or ledger.production_switch_authorized):
            raise MergeStrategyAdaptationError("Stage 169 ledger contains forbidden authority")
        if (not _HEX.fullmatch(ledger.digest) or not _HEX.fullmatch(ledger.evaluation_suite_digest)
                or _ledger_digest(ledger) != ledger.digest):
            raise MergeStrategyAdaptationError("Stage 169 ledger digest does not match its contents")
        if (ledger.generation_count < 1 or ledger.latest_generation < ledger.first_generation
                or ledger.generation_count != ledger.latest_generation - ledger.first_generation + 1):
            raise MergeStrategyAdaptationError("Stage 169 generation lineage is invalid")
        if (not isinstance(max_strategies, int) or isinstance(max_strategies, bool)
                or not 1 <= max_strategies <= 16
                or not isinstance(minimum_observations, int) or isinstance(minimum_observations, bool)
                or not 1 <= minimum_observations <= 1000):
            raise MergeStrategyAdaptationError("strategy bounds are invalid")
        if (not math.isfinite(exploration_floor) or not 0.05 <= exploration_floor <= 0.30
                or not math.isfinite(maximum_strategy_share) or not 0.20 <= maximum_strategy_share <= 0.80):
            raise MergeStrategyAdaptationError("allocation bounds are invalid")
        if len(ledger.strategy_history) > 64 or len(ledger.candidate_history) > 2048:
            raise MergeStrategyAdaptationError("lineage ledger exceeds strategy or candidate capacity")

        rows = []
        seen = set()
        for item in ledger.strategy_history:
            if item.strategy in seen or item.strategy not in (_PARAMETER | _ORCHESTRATION):
                raise MergeStrategyAdaptationError("unknown or duplicate merge strategy")
            seen.add(item.strategy)
            if (not isinstance(item.observed_candidates, int) or isinstance(item.observed_candidates, bool)
                    or item.observed_candidates < 0
                    or not 0 <= item.survivors <= item.observed_candidates
                    or not 0 <= item.retirement_proposals <= item.observed_candidates
                    or not 0 <= item.reexploration_events <= item.observed_candidates
                    or not math.isfinite(item.survival_rate)
                    or not 0 <= item.survival_rate <= 1):
                raise MergeStrategyAdaptationError("strategy history counters or rates are invalid")
            if item.observed_candidates == 0:
                continue
            survival = item.survivors / item.observed_candidates
            retirement = item.retirement_proposals / item.observed_candidates
            reexploration = item.reexploration_events / item.observed_candidates
            if abs(survival - item.survival_rate) > 1e-9:
                raise MergeStrategyAdaptationError("strategy survival rate does not match its counters")
            # Beta(1,1) smoothing avoids overreacting to tiny samples.
            confidence = item.observed_candidates / (item.observed_candidates + 4.0)
            priority = (survival * 0.65) + ((1.0 - retirement) * 0.20) + (reexploration * 0.15)
            priority *= confidence
            rationale = (
                "historical survivor evidence; parameter compatibility must be revalidated"
                if item.strategy in _PARAMETER else
                "orchestration-only fallback; never route to tensor or weight merging"
            )
            rows.append((item.strategy, item.strategy in _PARAMETER, item.observed_candidates,
                         survival, retirement, reexploration, confidence, priority, rationale))
        if not rows:
            raise MergeStrategyAdaptationError("no measured strategy history is available")
        rows.sort(key=lambda x: (-x[7], x[0]))
        rows = rows[:max_strategies]
        # Reserve a bounded exploration share; distribute the rest by evidence score.
        exploration = min(exploration_floor, 0.30)
        exploitation = 1.0 - exploration
        total_priority = sum(max(x[7], 0.001) for x in rows)
        raw = [exploitation * max(x[7], 0.001) / total_priority for x in rows]
        shares = [min(x, maximum_strategy_share) for x in raw]
        remaining = 1.0 - exploration - sum(shares)
        while remaining > 1e-9:
            eligible = [i for i, x in enumerate(shares) if x < maximum_strategy_share - 1e-9]
            if not eligible:
                # If caps bind, preserve the unallocated amount as exploration.
                exploration += remaining
                remaining = 0.0
                break
            weight = sum(max(rows[i][7], 0.001) for i in eligible)
            for i in eligible:
                addition = min(maximum_strategy_share - shares[i],
                               remaining * max(rows[i][7], 0.001) / weight)
                shares[i] += addition
            new_remaining = 1.0 - exploration - sum(shares)
            if new_remaining >= remaining - 1e-12:
                exploration += remaining
                remaining = 0.0
            else:
                remaining = max(0.0, new_remaining)
        allocations = tuple(MergeStrategyAllocation(
            row[0], "PARAMETER_MERGE" if row[1] else "ORCHESTRATION_ONLY",
            row[2], row[3], row[4], row[5], row[6], row[7], shares[i], row[8],
        ) for i, row in enumerate(rows))
        parameter_share = sum(x.evaluation_share for x in allocations if x.strategy_class == "PARAMETER_MERGE")
        orchestration_share = sum(x.evaluation_share for x in allocations if x.strategy_class == "ORCHESTRATION_ONLY")
        digest = _plan_digest(
            ledger.digest, ledger.evaluation_suite_digest, ledger.latest_generation,
            ledger.latest_generation + 1, allocations, parameter_share, orchestration_share, exploration,
        )
        return EvolutionaryMergeStrategyPlan(
            ledger.digest, ledger.evaluation_suite_digest, ledger.latest_generation,
            ledger.latest_generation + 1, allocations, parameter_share,
            orchestration_share, exploration, digest,
        )


__all__ = [
    "MergeStrategyAdaptationError", "MergeStrategyAllocation",
    "EvolutionaryMergeStrategyPlan", "EvolutionaryMergeStrategyAdapter",
]
