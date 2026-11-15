"""Stage 169: bounded append-only cross-generation survival ledger.

Verifies Stage 168 proposal digests and adjacent generation lineage, then
summarizes survival, retirement proposals, stagnation, and strategy diversity.
The ledger is a proposal artifact and never advances or activates a generation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

from .ai_factory_stage168_generation_survival_reexploration import (
    GenerationSurvivalProposal,
)

_HEX = re.compile(r"[0-9a-f]{64}")


class EvolutionaryLineageLedgerError(ValueError):
    """Raised when generation history is malformed, replayed, or unsafe."""


@dataclass(frozen=True)
class CandidateHistory:
    candidate_id: str
    strategy: str
    first_seen_generation: int
    last_seen_generation: int
    survived_generations: int
    retirement_proposals: int
    reexploration_events: int
    last_status: str


@dataclass(frozen=True)
class StrategyHistory:
    strategy: str
    observed_candidates: int
    survivors: int
    retirement_proposals: int
    reexploration_events: int
    survival_rate: float


@dataclass(frozen=True)
class EvolutionaryLineageLedger:
    evaluation_suite_digest: str
    first_generation: int
    latest_generation: int
    generation_count: int
    candidate_history: tuple[CandidateHistory, ...]
    strategy_history: tuple[StrategyHistory, ...]
    improved_generations: int
    stagnant_generations: int
    regressed_generations: int
    digest: str
    append_only_proposal: bool = True
    history_rewrite_authorized: bool = False
    survival_selection_authorized: bool = False
    retirement_executed: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _proposal_payload(report: GenerationSurvivalProposal) -> dict:
    return {
        "cohort": report.source_cohort_digest,
        "suite": report.evaluation_suite_digest,
        "source_generation": report.source_generation,
        "proposed_generation": report.proposed_generation,
        "fates": [(x.candidate_id, x.strategy, x.status, x.repeat_count, x.evaluator_count,
                   x.quality_delta, x.safety_floor, x.latency_ratio, x.memory_ratio, x.reason)
                  for x in report.fates],
        "reexploration": [(x.strategy, x.trigger, x.allocation, x.diagnostic_dimensions)
                          for x in report.reexploration],
    }


def proposal_digest(report: GenerationSurvivalProposal) -> str:
    return hashlib.sha256(json.dumps(
        _proposal_payload(report), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


class EvolutionaryLineageLedgerBuilder:
    """Aggregates authenticated Stage 168 outcomes across adjacent generations."""

    def build(
        self,
        proposals: tuple[GenerationSurvivalProposal, ...],
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_generations: int = 32,
        max_candidates: int = 2048,
    ) -> EvolutionaryLineageLedger:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionaryLineageLedgerError("HOLD, kill switch, or unavailable budget blocks ledger build")
        if not isinstance(proposals, tuple) or not 1 <= len(proposals) <= 32:
            raise EvolutionaryLineageLedgerError("bounded tuple of generation proposals is required")
        if (not isinstance(max_generations, int) or isinstance(max_generations, bool)
                or not 1 <= max_generations <= 32
                or not isinstance(max_candidates, int) or isinstance(max_candidates, bool)
                or not 1 <= max_candidates <= 2048 or len(proposals) > max_generations):
            raise EvolutionaryLineageLedgerError("ledger capacity is outside configured bounds")

        suite = None
        seen_cohorts, seen_candidate_generation = set(), set()
        candidate_rows: dict[str, dict] = {}
        strategy_rows: dict[str, dict] = {}
        generation_labels = []
        for report in proposals:
            if not isinstance(report, GenerationSurvivalProposal):
                raise EvolutionaryLineageLedgerError("typed Stage 168 survival proposal required")
            if (report.proposal_only is not True or report.survival_selection_authorized
                    or report.retirement_executed or report.experiment_execution_authorized
                    or report.model_merge_authorized or report.weight_mutation_authorized
                    or report.generation_advanced or report.model_activated
                    or report.production_switch_authorized):
                raise EvolutionaryLineageLedgerError("Stage 168 proposal contains forbidden authority")
            if (not _valid_digest(report.source_cohort_digest)
                    or not _valid_digest(report.evaluation_suite_digest)
                    or not _valid_digest(report.digest)
                    or proposal_digest(report) != report.digest):
                raise EvolutionaryLineageLedgerError("Stage 168 proposal digest is invalid")
            if (not isinstance(report.source_generation, int) or isinstance(report.source_generation, bool)
                    or report.proposed_generation != report.source_generation + 1):
                raise EvolutionaryLineageLedgerError("generation lineage is not adjacent")
            if suite is None:
                suite = report.evaluation_suite_digest
            elif report.evaluation_suite_digest != suite:
                raise EvolutionaryLineageLedgerError("frozen evaluation suite drift")
            if report.source_cohort_digest in seen_cohorts:
                raise EvolutionaryLineageLedgerError("duplicate cohort replay")
            seen_cohorts.add(report.source_cohort_digest)
            generation = report.proposed_generation
            generation_labels.append(generation)
            if len(report.fates) > 64 or len(report.reexploration) > 64:
                raise EvolutionaryLineageLedgerError("generation proposal exceeds per-generation capacity")
            local_ids = set()
            for fate in report.fates:
                if (not fate.candidate_id or len(fate.candidate_id) > 128
                        or not fate.strategy or len(fate.strategy) > 64
                        or fate.status not in {"SURVIVE", "RETIRE", "REEXPLORE"}):
                    raise EvolutionaryLineageLedgerError("candidate fate is invalid")
                key = (fate.candidate_id, generation)
                if key in seen_candidate_generation or fate.candidate_id in local_ids:
                    raise EvolutionaryLineageLedgerError("duplicate candidate fate in generation")
                seen_candidate_generation.add(key)
                local_ids.add(fate.candidate_id)
                row = candidate_rows.setdefault(fate.candidate_id, {
                    "strategy": fate.strategy, "first": generation, "last": generation,
                    "survived": 0, "retired": 0, "reexplored": 0, "status": fate.status,
                })
                if row["strategy"] != fate.strategy or generation <= row["last"]:
                    raise EvolutionaryLineageLedgerError("candidate identity changed strategy or lineage order")
                row["last"] = generation
                row["status"] = fate.status
                row["survived"] += fate.status == "SURVIVE"
                row["retired"] += fate.status == "RETIRE"
                row["reexplored"] += fate.status == "REEXPLORE"
                sr = strategy_rows.setdefault(fate.strategy, {
                    "observed": 0, "survivors": 0, "retired": 0, "reexplored": 0,
                })
                sr["observed"] += 1
                sr["survivors"] += fate.status == "SURVIVE"
                sr["retired"] += fate.status == "RETIRE"
                sr["reexplored"] += fate.status == "REEXPLORE"
            if len(candidate_rows) > max_candidates:
                raise EvolutionaryLineageLedgerError("candidate history capacity exceeded")

        if len(set(generation_labels)) != len(generation_labels):
            raise EvolutionaryLineageLedgerError("duplicate generation evidence")
        ordered = sorted(generation_labels)
        if any(b != a + 1 for a, b in zip(ordered, ordered[1:])):
            raise EvolutionaryLineageLedgerError("generation history must be contiguous and adjacent")
        candidates = tuple(CandidateHistory(
            key, row["strategy"], row["first"], row["last"], row["survived"],
            row["retired"], row["reexplored"], row["status"],
        ) for key, row in sorted(candidate_rows.items()))
        strategies = tuple(StrategyHistory(
            key, row["observed"], row["survivors"], row["retired"], row["reexplored"],
            row["survivors"] / row["observed"],
        ) for key, row in sorted(strategy_rows.items()))
        generation_status = []
        for report in proposals:
            statuses = [x.status for x in report.fates]
            if not statuses or all(x == "REEXPLORE" for x in statuses):
                generation_status.append("STAGNANT")
            elif any(x == "RETIRE" for x in statuses) and not any(x == "SURVIVE" for x in statuses):
                generation_status.append("REGRESSED")
            elif any(x == "SURVIVE" for x in statuses):
                generation_status.append("IMPROVED")
            else:
                generation_status.append("STAGNANT")
        improved = generation_status.count("IMPROVED")
        stagnant = generation_status.count("STAGNANT")
        regressed = generation_status.count("REGRESSED")
        payload = {
            "suite": suite, "first": min(ordered), "latest": max(ordered),
            "generations": ordered,
            "candidates": [(x.candidate_id, x.strategy, x.first_seen_generation,
                            x.last_seen_generation, x.survived_generations,
                            x.retirement_proposals, x.reexploration_events, x.last_status)
                           for x in candidates],
            "strategies": [(x.strategy, x.observed_candidates, x.survivors,
                            x.retirement_proposals, x.reexploration_events, x.survival_rate)
                           for x in strategies],
            "improved": improved, "stagnant": stagnant, "regressed": regressed,
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return EvolutionaryLineageLedger(
            suite, min(ordered), max(ordered), len(ordered), candidates, strategies,
            improved, stagnant, regressed, digest,
        )


__all__ = [
    "EvolutionaryLineageLedgerError", "CandidateHistory", "StrategyHistory",
    "EvolutionaryLineageLedger", "EvolutionaryLineageLedgerBuilder", "proposal_digest",
]
