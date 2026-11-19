"""Stage 163: failure-informed, bounded exploration planning for recursive evolution.

Consumes an independently attested Stage 158 tournament and Stage 162 learned policy.
It turns reproducibility, safety, regression, and evidence-shortage signals into
proposal-only next-trial exploration guidance. It never runs experiments or changes models.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from .ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport
from .ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionarySelectionPolicy,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class ExplorationPlanningError(ValueError):
    """Raised when tournament evidence cannot safely inform exploration."""


@dataclass(frozen=True)
class TournamentAttestation:
    report_digest: str
    evaluation_suite_digest: str
    source_generation: int
    evaluator_id: str
    signature: str


@dataclass(frozen=True)
class StrategyFailureProfile:
    strategy: str
    observations: int
    repeatability_failures: int
    safety_failures: int
    regression_failures: int
    evidence_shortfalls: int
    diagnostic_reasons: tuple[str, ...]
    exploration_share: float
    recommended_repeats: int
    retain_as_candidate: bool


@dataclass(frozen=True)
class AdaptiveExplorationPlan:
    tournament_digest: str
    policy_digest: str
    evaluation_suite_digest: str
    source_generation: int
    profiles: tuple[StrategyFailureProfile, ...]
    rejected_evidence_count: int
    total_exploration_share: float
    plan_digest: str
    proposal_only: bool = True
    experiment_execution_authorized: bool = False
    selection_authorized: bool = False
    model_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


class FailureInformedExplorationPlanner:
    """Builds deterministic retry/diversity guidance from verified tournament reports."""

    def plan(
        self,
        tournament: MergeTournamentReport,
        attestation: TournamentAttestation,
        policy: EvolutionarySelectionPolicy,
        *,
        verify_attestation: Callable[[MergeTournamentReport, TournamentAttestation], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_strategies: int = 16,
    ) -> AdaptiveExplorationPlan:
        if hold_active or kill_switch_active or not budget_available:
            raise ExplorationPlanningError("HOLD, kill switch, or unavailable budget blocks exploration planning")
        if not isinstance(tournament, MergeTournamentReport) or not isinstance(policy, EvolutionarySelectionPolicy):
            raise ExplorationPlanningError("typed Stage 158 tournament and Stage 162 policy are required")
        if not isinstance(attestation, TournamentAttestation) or not callable(verify_attestation):
            raise ExplorationPlanningError("independent tournament attestation and verifier are required")
        if (not tournament.proposal_only or tournament.execution_authorized
                or tournament.merge_authorized or tournament.weight_mutation_authorized
                or tournament.generation_advanced or tournament.model_activated
                or tournament.production_switch_authorized):
            raise ExplorationPlanningError("tournament contains forbidden authority")
        if (not policy.proposal_only or policy.selection_authorized or policy.execution_authorized
                or policy.model_mutation_authorized or policy.model_activated):
            raise ExplorationPlanningError("Stage 162 policy contains forbidden authority")
        if (not _valid_digest(tournament.digest) or not _valid_digest(tournament.evaluation_suite_digest)
                or not _valid_digest(policy.policy_digest)
                or attestation.report_digest != tournament.digest
                or attestation.evaluation_suite_digest != tournament.evaluation_suite_digest
                or policy.evaluation_suite_digest != tournament.evaluation_suite_digest
                or not _valid_digest(attestation.report_digest)
                or not _valid_digest(attestation.evaluation_suite_digest)
                or not _ID.fullmatch(attestation.evaluator_id or "")
                or not isinstance(attestation.source_generation, int)
                or isinstance(attestation.source_generation, bool) or attestation.source_generation < 0
                or not isinstance(attestation.signature, str) or not attestation.signature.strip()
                or len(attestation.signature) > 8192):
            raise ExplorationPlanningError("attestation, generation, or frozen-suite binding is invalid")
        if not verify_attestation(tournament, attestation):
            raise ExplorationPlanningError("independent tournament attestation verification failed")
        if not tournament.scores or len(tournament.scores) > 1024 or len(tournament.proposed_preferences) > 1024:
            raise ExplorationPlanningError("tournament score set is empty or exceeds planning capacity")
        if not isinstance(max_strategies, int) or isinstance(max_strategies, bool) or not 1 <= max_strategies <= 32:
            raise ExplorationPlanningError("max_strategies must be between 1 and 32")

        policy_strategies = {x.strategy for x in policy.learnings}
        grouped: dict[str, list] = {}
        seen = set()
        for score in tournament.scores:
            if score.strategy not in policy_strategies:
                # A new strategy with no history is still eligible for exploration.
                strategy = score.strategy
            else:
                strategy = score.strategy
            if not isinstance(strategy, str) or not strategy or len(strategy) > 64:
                raise ExplorationPlanningError("invalid strategy identity in tournament")
            if (not isinstance(score.trial_count, int) or isinstance(score.trial_count, bool)
                    or score.trial_count < 1 or not _valid_digest(score.score_digest)):
                raise ExplorationPlanningError("strategy score count or digest is invalid")
            if score.score_digest in seen:
                raise ExplorationPlanningError("duplicate strategy score digest")
            seen.add(score.score_digest)
            fitness = score.median_fitness
            metrics = (fitness.accuracy, fitness.instruction_following, fitness.safety,
                       fitness.latency_ms, fitness.memory_mb)
            if (fitness.evaluation_suite_digest != tournament.evaluation_suite_digest
                    or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in metrics)
                    or not 0 <= fitness.accuracy <= 1 or not 0 <= fitness.instruction_following <= 1
                    or not 0 <= fitness.safety <= 1 or fitness.latency_ms <= 0
                    or fitness.memory_mb <= 0 or fitness.regression_count < 0):
                raise ExplorationPlanningError("strategy score metrics are invalid or suite-incompatible")
            grouped.setdefault(strategy, []).append(score)
        if len(grouped) > max_strategies:
            raise ExplorationPlanningError("strategy count exceeds exploration planning capacity")

        profiles = []
        base_share = 1.0 / max(1, len(grouped))
        for strategy, scores in sorted(grouped.items()):
            repeat_fail = sum(not x.repeatable for x in scores)
            safety_fail = sum(x.median_fitness.safety < 0.95 for x in scores)
            regression_fail = sum(x.median_fitness.regression_count > 0 for x in scores)
            evidence_shortfall = 1 if strategy in {x[1] for x in tournament.proposed_preferences} and not any(
                x.repeatable and x.pareto_optimal for x in scores
            ) else 0
            reasons = sorted({
                reason for score in scores for reason in score.repeatability_reasons
            })
            if safety_fail:
                reasons.append("safety floor unmet; isolate and diagnose before any candidate consideration")
            if regression_fail:
                reasons.append("evaluation regression observed; require a fresh independent diagnostic trial")
            if evidence_shortfall:
                reasons.append("preferred strategy lacks a repeatable Pareto-eligible evidence set")
            failures = repeat_fail + safety_fail + regression_fail + evidence_shortfall
            # Failures increase diagnostic exploration, not trust or production priority.
            diagnostic_boost = min(0.15, 0.05 * failures)
            share = min(0.40, base_share + diagnostic_boost)
            retain = not safety_fail and not regression_fail and any(x.repeatable for x in scores)
            repeats = min(4, max(2, 2 + min(2, failures)))
            profiles.append(StrategyFailureProfile(
                strategy=strategy,
                observations=sum(x.trial_count for x in scores),
                repeatability_failures=repeat_fail,
                safety_failures=safety_fail,
                regression_failures=regression_fail,
                evidence_shortfalls=evidence_shortfall,
                diagnostic_reasons=tuple(reasons),
                exploration_share=share,
                recommended_repeats=repeats,
                retain_as_candidate=retain,
            ))

        # Normalize shares so the bounded plan never allocates more than 100%.
        total = sum(x.exploration_share for x in profiles)
        if total > 1.0:
            profiles = [StrategyFailureProfile(
                x.strategy, x.observations, x.repeatability_failures, x.safety_failures,
                x.regression_failures, x.evidence_shortfalls, x.diagnostic_reasons,
                x.exploration_share / total, x.recommended_repeats, x.retain_as_candidate,
            ) for x in profiles]
            total = 1.0

        payload = {
            "tournament": tournament.digest,
            "policy": policy.policy_digest,
            "suite": tournament.evaluation_suite_digest,
            "generation": attestation.source_generation,
            "rejected": len(tournament.rejected_trial_digests),
            "profiles": [{
                "strategy": x.strategy, "observations": x.observations,
                "repeatability_failures": x.repeatability_failures,
                "safety_failures": x.safety_failures,
                "regression_failures": x.regression_failures,
                "evidence_shortfalls": x.evidence_shortfalls,
                "reasons": list(x.diagnostic_reasons),
                "share": x.exploration_share, "repeats": x.recommended_repeats,
                "retain": x.retain_as_candidate,
            } for x in profiles],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return AdaptiveExplorationPlan(
            tournament.digest, policy.policy_digest, tournament.evaluation_suite_digest,
            attestation.source_generation, tuple(profiles), len(tournament.rejected_trial_digests),
            total, digest,
        )


__all__ = [
    "ExplorationPlanningError", "TournamentAttestation", "StrategyFailureProfile",
    "AdaptiveExplorationPlan", "FailureInformedExplorationPlanner",
]
