"""Stage 166: recursive next-generation model/strategy ranking advice.

Reweights only already Pareto-eligible, independently repeatable Stage 158
preferences using authenticated Stage 165 outcomes and bounded Stage 162 priors.
It never creates evidence, promotes unsafe candidates, or advances a generation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

from .ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport
from .ai_factory_stage162_evolutionary_policy_learning import EvolutionarySelectionPolicy
from .ai_factory_stage165_recursive_evolution_feedback import (
    RecursiveEvolutionFeedbackSnapshot, RecursiveTrialRecord,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ALLOWED = {"slerp", "ties", "dare", "task_arithmetic", "lora",
            "parameter_merge", "multi_model_orchestration"}


class RecursiveModelSelectionError(ValueError):
    """Raised when recursive ranking inputs are inconsistent or unsafe."""


@dataclass(frozen=True)
class CandidateStrategyAdvice:
    candidate_id: str
    strategy: str
    historical_prior: float
    recursive_feedback_adjustment: float
    combined_score: float
    evidence_observations: int
    improved_observations: int
    regression_observations: int
    safety_failures: int
    stagnant_observations: int


@dataclass(frozen=True)
class RecursiveModelSelectionReport:
    source_feedback_digest: str
    source_policy_digest: str
    source_tournament_digest: str
    evaluation_suite_digest: str
    ordered_preferences: tuple[tuple[str, str], ...]
    advice: tuple[CandidateStrategyAdvice, ...]
    digest: str
    proposal_only: bool = True
    candidate_selection_authorized: bool = False
    experiment_execution_authorized: bool = False
    model_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _record_digest(record: RecursiveTrialRecord) -> str:
    canonical = {
        "outcome": record.outcome_digest, "evidence": record.evidence_digest,
        "design": record.design_digest, "plan": record.plan_id,
        "recipe": record.recipe_digest, "strategy": record.strategy,
        "generation": record.source_generation, "classification": record.classification,
        "metrics": record.metrics, "baseline": record.baseline_metrics,
        "lessons": list(record.lessons),
    }
    return _digest(canonical)


def _snapshot_digest(snapshot: RecursiveEvolutionFeedbackSnapshot) -> str:
    payload = {
        "records": [x.record_digest for x in snapshot.records],
        "summaries": [{
            "strategy": x.strategy, "observations": x.observations,
            "improved": x.improved, "regressed": x.regressed,
            "safety_failures": x.safety_failures, "stagnant": x.stagnant,
            "repeatability_required": x.repeatability_required,
            "guidance": list(x.next_generation_guidance),
        } for x in snapshot.summaries],
        "suite": snapshot.evaluation_suite_digest,
    }
    return _digest(payload)


def _policy_digest(policy: EvolutionarySelectionPolicy) -> str:
    payload = {
        "feedback": policy.feedback_snapshot_digest,
        "suite": policy.evaluation_suite_digest,
        "learnings": [{
            "strategy": x.strategy, "count": x.observations,
            "improved": x.improved_observations, "quality": x.quality_mean,
            "safety": x.safety_mean, "latency": x.latency_mean_ms,
            "memory": x.memory_mean_mb, "confidence": x.confidence,
            "prior": x.prior_score, "records": list(x.evidence_record_digests),
        } for x in policy.learnings],
    }
    return _digest(payload)


def _validate_snapshot(snapshot: RecursiveEvolutionFeedbackSnapshot, suite: str) -> dict[str, tuple[int, int, int, int, int]]:
    if (snapshot.proposal_only is not True or snapshot.generation_advanced is not False
            or snapshot.model_activated is not False or snapshot.model_mutation_authorized is not False
            or snapshot.production_switch_authorized is not False):
        raise RecursiveModelSelectionError("Stage 165 snapshot contains forbidden authority")
    if snapshot.evaluation_suite_digest != suite or not _valid_digest(snapshot.digest):
        raise RecursiveModelSelectionError("Stage 165 snapshot suite or digest is invalid")
    if not snapshot.records or len(snapshot.records) > 4096 or len(snapshot.summaries) > 64:
        raise RecursiveModelSelectionError("Stage 165 snapshot is empty or exceeds bounds")
    seen_outcomes = set()
    counts: dict[str, list[int]] = {}
    for record in snapshot.records:
        if (record.pending_human_approval is not True or record.generation_advanced is not False
                or record.model_activated is not False or record.model_mutation_authorized is not False
                or record.production_switch_authorized is not False):
            raise RecursiveModelSelectionError("Stage 165 trial record contains forbidden authority")
        if (not all(_valid_digest(x) for x in (
                record.outcome_digest, record.evidence_digest, record.design_digest,
                record.recipe_digest, record.record_digest))
                or not record.plan_id or not record.strategy or record.strategy not in _ALLOWED
                or record.proposed_generation != record.source_generation + 1
                or record.source_generation < 0):
            raise RecursiveModelSelectionError("Stage 165 record identity or generation is invalid")
        if record.outcome_digest in seen_outcomes:
            raise RecursiveModelSelectionError("duplicate Stage 165 outcome in snapshot")
        seen_outcomes.add(record.outcome_digest)
        if _record_digest(record) != record.record_digest:
            raise RecursiveModelSelectionError("Stage 165 record digest does not match its contents")
        if record.classification not in {"IMPROVED", "REGRESSED", "SAFETY_FAILURE", "STAGNANT"}:
            raise RecursiveModelSelectionError("unknown Stage 165 outcome classification")
        bucket = counts.setdefault(record.strategy, [0, 0, 0, 0, 0])
        bucket[0] += 1
        if record.classification == "IMPROVED":
            bucket[1] += 1
        elif record.classification == "REGRESSED":
            bucket[2] += 1
        elif record.classification == "SAFETY_FAILURE":
            bucket[3] += 1
        elif record.classification == "STAGNANT":
            bucket[4] += 1
    summary_by_strategy = {}
    for summary in snapshot.summaries:
        if summary.strategy in summary_by_strategy or summary.strategy not in _ALLOWED:
            raise RecursiveModelSelectionError("duplicate or unsupported Stage 165 strategy summary")
        expected = counts.get(summary.strategy, [0, 0, 0, 0, 0])
        actual = [summary.observations, summary.improved, summary.regressed,
                  summary.safety_failures, summary.stagnant]
        if actual != expected or summary.repeatability_required < 0:
            raise RecursiveModelSelectionError("Stage 165 summary does not match its append-only records")
        summary_by_strategy[summary.strategy] = tuple(actual)
    if set(summary_by_strategy) != set(counts):
        raise RecursiveModelSelectionError("Stage 165 summaries do not cover the exact record strategies")
    if _snapshot_digest(snapshot) != snapshot.digest:
        raise RecursiveModelSelectionError("Stage 165 snapshot digest does not match contents")
    return summary_by_strategy


class RecursiveModelSelectionAdvisor:
    """Combines prior and failure-informed adjustments as ranking-only advice."""

    def rank(
        self,
        feedback: RecursiveEvolutionFeedbackSnapshot,
        policy: EvolutionarySelectionPolicy,
        tournament: MergeTournamentReport,
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_feedback_adjustment: float = 0.10,
    ) -> RecursiveModelSelectionReport:
        if hold_active or kill_switch_active or not budget_available:
            raise RecursiveModelSelectionError("HOLD, kill switch, or unavailable budget blocks recursive ranking")
        if not isinstance(feedback, RecursiveEvolutionFeedbackSnapshot):
            raise RecursiveModelSelectionError("typed Stage 165 recursive feedback is required")
        if not isinstance(policy, EvolutionarySelectionPolicy):
            raise RecursiveModelSelectionError("typed Stage 162 evolutionary policy is required")
        if not isinstance(tournament, MergeTournamentReport):
            raise RecursiveModelSelectionError("typed Stage 158 tournament is required")
        if (not 0 < max_feedback_adjustment <= 0.10
                or not math.isfinite(max_feedback_adjustment)):
            raise RecursiveModelSelectionError("feedback influence must be in (0, 0.10]")
        if (not policy.proposal_only or policy.selection_authorized or policy.execution_authorized
                or policy.model_mutation_authorized or policy.model_activated):
            raise RecursiveModelSelectionError("Stage 162 policy contains forbidden authority")
        if (not tournament.proposal_only or tournament.execution_authorized
                or tournament.merge_authorized or tournament.weight_mutation_authorized
                or tournament.generation_advanced or tournament.model_activated
                or tournament.production_switch_authorized):
            raise RecursiveModelSelectionError("Stage 158 tournament contains forbidden authority")
        if (not _valid_digest(policy.policy_digest) or _policy_digest(policy) != policy.policy_digest
                or not _valid_digest(tournament.digest)
                or not _valid_digest(tournament.evaluation_suite_digest)
                or policy.evaluation_suite_digest != tournament.evaluation_suite_digest
                or feedback.evaluation_suite_digest != tournament.evaluation_suite_digest):
            raise RecursiveModelSelectionError("policy, tournament, and feedback are not bound to one frozen suite")
        history = _validate_snapshot(feedback, tournament.evaluation_suite_digest)

        priors = {}
        for learning in policy.learnings:
            if (learning.strategy not in _ALLOWED or learning.strategy in priors
                    or not isinstance(learning.prior_score, (int, float))
                    or isinstance(learning.prior_score, bool)
                    or not math.isfinite(learning.prior_score)
                    or abs(learning.prior_score) > policy.max_prior_influence):
                raise RecursiveModelSelectionError("Stage 162 learned prior is duplicate, invalid, or unbounded")
            priors[learning.strategy] = float(learning.prior_score)
        if not isinstance(policy.max_prior_influence, (int, float)) or not 0 < policy.max_prior_influence <= 0.15:
            raise RecursiveModelSelectionError("Stage 162 prior influence bound is invalid")

        scores = {(x.candidate_id, x.strategy): x for x in tournament.scores}
        if len(scores) != len(tournament.scores):
            raise RecursiveModelSelectionError("duplicate Stage 158 strategy score")
        proposed = tuple(tournament.proposed_preferences)
        if len(set(proposed)) != len(proposed):
            raise RecursiveModelSelectionError("duplicate Stage 158 proposed preference")
        advice = []
        ranked = []
        for candidate_id, strategy in proposed:
            score = scores.get((candidate_id, strategy))
            if score is None or not score.pareto_optimal or not score.repeatable:
                continue
            if score.median_fitness.safety < 0.95 or score.median_fitness.regression_count != 0:
                continue
            observations, improved, regressed, safety, stagnant = history.get(strategy, (0, 0, 0, 0, 0))
            if observations:
                # Smoothed empirical rates avoid extreme updates from a single trial.
                adjustment = max_feedback_adjustment * (
                    (improved - regressed - 2 * safety - 0.5 * stagnant) / (observations + 4)
                )
            else:
                adjustment = 0.0
            prior = priors.get(strategy, 0.0)
            combined = max(-policy.max_prior_influence, min(policy.max_prior_influence, prior + adjustment))
            advice.append(CandidateStrategyAdvice(
                candidate_id, strategy, prior, adjustment, combined,
                observations, improved, regressed, safety, stagnant,
            ))
            ranked.append((combined, candidate_id, strategy))
        ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
        ordered = tuple((candidate_id, strategy) for _, candidate_id, strategy in ranked)
        payload = {
            "feedback": feedback.digest, "policy": policy.policy_digest,
            "tournament": tournament.digest, "suite": tournament.evaluation_suite_digest,
            "ordered": ordered,
            "advice": [{
                "candidate": x.candidate_id, "strategy": x.strategy,
                "prior": x.historical_prior, "feedback": x.recursive_feedback_adjustment,
                "combined": x.combined_score, "observations": x.evidence_observations,
                "improved": x.improved_observations, "regressed": x.regression_observations,
                "safety": x.safety_failures, "stagnant": x.stagnant_observations,
            } for x in advice],
        }
        digest = _digest(payload)
        return RecursiveModelSelectionReport(
            feedback.digest, policy.policy_digest, tournament.digest,
            tournament.evaluation_suite_digest, ordered, tuple(advice), digest,
        )


__all__ = [
    "RecursiveModelSelectionError", "CandidateStrategyAdvice",
    "RecursiveModelSelectionReport", "RecursiveModelSelectionAdvisor",
]
