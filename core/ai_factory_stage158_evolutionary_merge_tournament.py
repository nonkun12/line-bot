"""Stage 158: evidence-backed evolutionary merge-strategy tournaments.

Consumes Stage 154 proposal plans and independently signed repeated trial evidence.
Ranks only comparable candidates; this module never executes merges or activates models.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from statistics import median
from typing import Callable, Sequence

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage154_merge_strategy_evaluation import (
    MergeEvaluationPlanReport, MergeAlgorithm,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
ORCHESTRATION = "multi_model_orchestration"


class MergeTournamentError(ValueError):
    """Raised when tournament evidence is incomplete, incomparable, or unsafe."""


@dataclass(frozen=True)
class StrategyTrialEvidence:
    trial_id: str
    plan_id: str
    candidate_id: str
    generation: int
    strategy: str
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    replicate: int
    evaluator_id: str
    evidence_digest: str
    fitness: Fitness
    signature: str


@dataclass(frozen=True)
class StrategyScore:
    candidate_id: str
    strategy: str
    trial_count: int
    evaluator_ids: tuple[str, ...]
    median_fitness: Fitness
    repeatable: bool
    repeatability_reasons: tuple[str, ...]
    pareto_optimal: bool
    score_digest: str


@dataclass(frozen=True)
class MergeTournamentReport:
    source_plan_digest: str
    evaluation_suite_digest: str
    scores: tuple[StrategyScore, ...]
    proposed_preferences: tuple[tuple[str, str], ...]
    rejected_trial_digests: tuple[str, ...]
    digest: str
    proposal_only: bool = True
    execution_authorized: bool = False
    merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _fitness_valid(value: Fitness, suite: str) -> None:
    if not isinstance(value, Fitness) or value.evaluation_suite_digest != suite:
        raise MergeTournamentError("trial fitness is not bound to the frozen suite")
    values = (value.accuracy, value.instruction_following, value.safety,
              value.latency_ms, value.memory_mb)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in values):
        raise MergeTournamentError("trial metrics must be finite numeric values")
    if not 0 <= value.accuracy <= 1 or not 0 <= value.instruction_following <= 1 or not 0 <= value.safety <= 1:
        raise MergeTournamentError("quality and safety scores must be in [0, 1]")
    if value.latency_ms <= 0 or value.memory_mb <= 0 or value.regression_count < 0:
        raise MergeTournamentError("resource metrics or regression count are invalid")


def _dominates(a: Fitness, b: Fitness) -> bool:
    left = (a.accuracy, a.instruction_following, a.safety, -a.latency_ms, -a.memory_mb, -a.regression_count)
    right = (b.accuracy, b.instruction_following, b.safety, -b.latency_ms, -b.memory_mb, -b.regression_count)
    return all(x >= y for x, y in zip(left, right)) and any(x > y for x, y in zip(left, right))


def _median_fitness(items: Sequence[StrategyTrialEvidence]) -> Fitness:
    first = items[0].fitness
    return Fitness(
        median(x.fitness.accuracy for x in items),
        median(x.fitness.instruction_following for x in items),
        median(x.fitness.safety for x in items),
        median(x.fitness.latency_ms for x in items),
        median(x.fitness.memory_mb for x in items),
        max(x.fitness.regression_count for x in items),
        first.evaluation_suite_digest,
    )


def _repeatability(items: Sequence[StrategyTrialEvidence]) -> tuple[bool, tuple[str, ...]]:
    reasons = []
    limits = (
        ("accuracy", 0.02), ("instruction_following", 0.02),
        ("safety", 0.01), ("latency_ms", 0.10), ("memory_mb", 0.10),
    )
    for field, relative_limit in limits:
        values = [getattr(x.fitness, field) for x in items]
        baseline = max(abs(median(values)), 1e-9)
        if (max(values) - min(values)) / baseline > relative_limit:
            reasons.append(f"{field} variance exceeds repeatability limit")
    if len({x.evaluator_id for x in items}) != len(items):
        reasons.append("replicates must use distinct independent evaluators")
    if any(x.fitness.safety < 0.95 or x.fitness.regression_count for x in items):
        reasons.append("safety floor or evaluation regression blocks strategy eligibility")
    return not reasons, tuple(reasons)


class EvolutionaryMergeTournament:
    """Bounded, deterministic tournament over repeated independently evaluated trials."""

    def __init__(self, *, min_repeats: int = 2, max_trials: int = 256) -> None:
        if not isinstance(min_repeats, int) or isinstance(min_repeats, bool) or not 2 <= min_repeats <= 8:
            raise ValueError("min_repeats must be between 2 and 8")
        if not isinstance(max_trials, int) or isinstance(max_trials, bool) or not 2 <= max_trials <= 1024:
            raise ValueError("max_trials must be between 2 and 1024")
        self._min_repeats = min_repeats
        self._max_trials = max_trials

    def evaluate(
        self,
        plans: MergeEvaluationPlanReport,
        trials: Sequence[StrategyTrialEvidence],
        *,
        verify_trial: Callable[[StrategyTrialEvidence], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> MergeTournamentReport:
        if hold_active or kill_switch_active or not budget_available:
            raise MergeTournamentError("HOLD, kill switch, or unavailable budget blocks tournament")
        if not isinstance(plans, MergeEvaluationPlanReport) or not plans.proposal_only:
            raise MergeTournamentError("proposal-only Stage 154 plan report is required")
        if (plans.tensors_read or plans.weights_modified or plans.inference_executed
                or plans.generation_advanced or plans.production_switch_authorized):
            raise MergeTournamentError("Stage 154 report contains forbidden execution authority")
        if not _valid_digest(plans.digest) or not _valid_digest(plans.evaluation_suite_digest):
            raise MergeTournamentError("source plan or suite digest is invalid")
        if not isinstance(trials, Sequence) or not trials or len(trials) > self._max_trials:
            raise MergeTournamentError("trial set is empty or exceeds tournament capacity")
        if not callable(verify_trial):
            raise MergeTournamentError("independent signature verifier is required")

        plan_by_id = {p.plan_id: p for p in plans.plans}
        if len(plan_by_id) != len(plans.plans):
            raise MergeTournamentError("duplicate Stage 154 plan identity")
        route_by_id = {f"orchestration:{r.candidate_id}": r for r in plans.orchestration_routes}
        if len(route_by_id) != len(plans.orchestration_routes):
            raise MergeTournamentError("duplicate orchestration route")
        seen_trials, seen_evidence, seen_replicates = set(), set(), set()
        grouped: dict[tuple[str, str], list[StrategyTrialEvidence]] = {}
        rejected = []
        for item in trials:
            if not isinstance(item, StrategyTrialEvidence):
                raise MergeTournamentError("typed signed trial evidence is required")
            if (not _valid_digest(item.evidence_digest) or not _valid_digest(item.candidate_artifact_digest)
                    or not _valid_digest(item.evaluation_suite_digest)
                    or not isinstance(item.signature, str) or not item.signature.strip() or len(item.signature) > 8192
                    or not _ID.fullmatch(item.trial_id or "") or not _ID.fullmatch(item.evaluator_id or "")
                    or item.replicate < 1):
                raise MergeTournamentError("trial identity, signature, digest, or replicate is invalid")
            if item.trial_id in seen_trials or item.evidence_digest in seen_evidence:
                raise MergeTournamentError("duplicate or replayed trial evidence")
            if item.evaluation_suite_digest != plans.evaluation_suite_digest:
                raise MergeTournamentError("evaluation suite drift")
            _fitness_valid(item.fitness, plans.evaluation_suite_digest)
            if not verify_trial(item):
                raise MergeTournamentError("independent trial signature verification failed")

            plan = plan_by_id.get(item.plan_id)
            route = route_by_id.get(item.plan_id)
            if plan is not None:
                expected = (plan.candidate_id, plan.generation, plan.algorithm.value,
                            plan.parent_model_ids, plan.parent_artifact_digests,
                            plan.candidate_artifact_digest, plan.evaluation_suite_digest)
                actual = (item.candidate_id, item.generation, item.strategy,
                          item.parent_model_ids, item.parent_artifact_digests,
                          item.candidate_artifact_digest, item.evaluation_suite_digest)
                if actual != expected:
                    raise MergeTournamentError("trial does not bind to exact Stage 154 plan lineage")
                if plan.execution_authorized or plan.merge_authorized or plan.activation_authorized:
                    raise MergeTournamentError("Stage 154 plan unexpectedly grants execution authority")
            elif route is not None:
                if (item.candidate_id != route.candidate_id or item.strategy != ORCHESTRATION
                        or item.generation < 1 or item.parent_model_ids or item.parent_artifact_digests
                        or item.plan_id != f"orchestration:{route.candidate_id}"):
                    raise MergeTournamentError("orchestration evidence must remain a no-weight-merge route")
            else:
                raise MergeTournamentError("trial references an unknown plan or orchestration route")

            key = (item.candidate_id, item.strategy)
            replicate_key = (key, item.replicate)
            if replicate_key in seen_replicates:
                raise MergeTournamentError("duplicate strategy replicate")
            seen_replicates.add(replicate_key)
            seen_trials.add(item.trial_id)
            seen_evidence.add(item.evidence_digest)
            grouped.setdefault(key, []).append(item)

        scores = []
        for (candidate_id, strategy), items in sorted(grouped.items()):
            if len(items) < self._min_repeats:
                rejected.extend(x.evidence_digest for x in items)
                continue
            lineage = {(x.generation, x.parent_model_ids, x.parent_artifact_digests,
                        x.candidate_artifact_digest, x.evaluation_suite_digest) for x in items}
            if len(lineage) != 1:
                raise MergeTournamentError("strategy replicates are not lineage-comparable")
            evaluator_ids = [x.evaluator_id for x in items]
            if len(set(evaluator_ids)) != len(evaluator_ids):
                raise MergeTournamentError("replicates must use distinct independent evaluators")
            evaluators = tuple(sorted(evaluator_ids))
            repeatable, reasons = _repeatability(items)
            aggregate = _median_fitness(items)
            payload = {
                "candidate": candidate_id, "strategy": strategy, "trials": sorted(x.evidence_digest for x in items),
                "median": [aggregate.accuracy, aggregate.instruction_following, aggregate.safety,
                           aggregate.latency_ms, aggregate.memory_mb, aggregate.regression_count],
                "repeatable": repeatable, "reasons": reasons, "suite": plans.evaluation_suite_digest,
            }
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            scores.append(StrategyScore(candidate_id, strategy, len(items), evaluators,
                                        aggregate, repeatable, reasons, False, digest))

        updated = []
        for score in scores:
            eligible = score.repeatable and score.median_fitness.safety >= 0.95 and score.median_fitness.regression_count == 0
            dominated = any(
                other.candidate_id == score.candidate_id and other.score_digest != score.score_digest
                and other.repeatable and other.median_fitness.safety >= 0.95
                and other.median_fitness.regression_count == 0
                and _dominates(other.median_fitness, score.median_fitness)
                for other in scores
            )
            updated.append(StrategyScore(
                score.candidate_id, score.strategy, score.trial_count, score.evaluator_ids,
                score.median_fitness, score.repeatable, score.repeatability_reasons,
                bool(eligible and not dominated), score.score_digest,
            ))
        preferences = tuple(sorted(
            (x.candidate_id, x.strategy) for x in updated if x.pareto_optimal
        ))
        payload = {
            "source": plans.digest, "suite": plans.evaluation_suite_digest,
            "scores": [x.score_digest for x in updated], "preferences": preferences,
            "rejected": sorted(rejected),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return MergeTournamentReport(
            plans.digest, plans.evaluation_suite_digest, tuple(updated), preferences,
            tuple(sorted(rejected)), digest,
        )


__all__ = [
    "MergeTournamentError", "StrategyTrialEvidence", "StrategyScore",
    "MergeTournamentReport", "EvolutionaryMergeTournament",
]
