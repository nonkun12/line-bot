"""Stage 162: evidence-backed learning policy for evolutionary strategy selection.

Learns bounded strategy priors only from Stage 161 receipts that bind to the exact
Stage 156 authenticated knowledge records. Outputs ranking advice, never changes
trial evidence, model weights, or activation/selection authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Sequence

from .ai_factory_stage156_authenticated_knowledge_transfer import GenerationKnowledge
from .ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport
from .ai_factory_stage161_verified_evolution_feedback import EvolutionFeedbackSnapshot

_HEX = re.compile(r"[0-9a-f]{64}")
_ALLOWED_STRATEGIES = {
    "slerp", "ties", "dare", "task_arithmetic", "lora",
    "parameter_merge", "multi_model_orchestration",
}


class EvolutionPolicyError(ValueError):
    """Raised when historical evolutionary evidence is invalid or incomparable."""


@dataclass(frozen=True)
class StrategyLearning:
    strategy: str
    observations: int
    improved_observations: int
    quality_mean: float
    safety_mean: float
    latency_mean_ms: float
    memory_mean_mb: float
    confidence: float
    prior_score: float
    evidence_record_digests: tuple[str, ...]


@dataclass(frozen=True)
class EvolutionarySelectionPolicy:
    feedback_snapshot_digest: str
    evaluation_suite_digest: str
    learnings: tuple[StrategyLearning, ...]
    policy_digest: str
    max_prior_influence: float = 0.15
    proposal_only: bool = True
    selection_authorized: bool = False
    execution_authorized: bool = False
    model_mutation_authorized: bool = False
    model_activated: bool = False


@dataclass(frozen=True)
class StrategyRankingAdvice:
    tournament_digest: str
    policy_digest: str
    ordered_preferences: tuple[tuple[str, str], ...]
    applied_prior_adjustments: tuple[tuple[str, str, float], ...]
    digest: str
    proposal_only: bool = True
    selection_authorized: bool = False
    model_activated: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


class EvolutionarySelectionPolicyLearner:
    """Derives conservative, bounded priors from authenticated experiment outcomes."""

    def learn(
        self,
        feedback: EvolutionFeedbackSnapshot,
        *,
        expected_suite_digest: str,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionarySelectionPolicy:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionPolicyError("HOLD, kill switch, or unavailable budget blocks policy learning")
        if not isinstance(feedback, EvolutionFeedbackSnapshot) or feedback.proposal_only is not True:
            raise EvolutionPolicyError("proposal-only Stage 161 feedback snapshot is required")
        if (feedback.generation_advanced is not False or feedback.model_activated is not False
                or feedback.knowledge.proposal_only is not True
                or feedback.knowledge.generation_advanced is not False
                or feedback.knowledge.model_activated is not False):
            raise EvolutionPolicyError("feedback ledger contains forbidden authority")
        if (not _valid_digest(feedback.digest) or not _valid_digest(feedback.knowledge.digest)
                or not _valid_digest(expected_suite_digest)):
            raise EvolutionPolicyError("feedback or evaluation-suite digest is invalid")
        if not feedback.knowledge.records or len(feedback.knowledge.records) > 4096:
            raise EvolutionPolicyError("knowledge ledger is empty or exceeds policy-learning capacity")
        if len(feedback.receipts) != len(feedback.knowledge.records):
            raise EvolutionPolicyError("every knowledge record must have exactly one Stage 161 receipt")

        receipts_by_record = {}
        for receipt in feedback.receipts:
            if (not _valid_digest(receipt.feedback_digest)
                    or not _valid_digest(receipt.knowledge_record_digest)
                    or not _valid_digest(receipt.proposal_digest)
                    or receipt.pending_human_approval is not True
                    or receipt.generation_advanced is not False
                    or receipt.model_activated is not False
                    or receipt.auto_adoption_authorized is not False
                    or receipt.production_switch_authorized is not False):
                raise EvolutionPolicyError("feedback receipt is invalid or carries authority")
            if receipt.knowledge_record_digest in receipts_by_record:
                raise EvolutionPolicyError("duplicate feedback receipt for knowledge record")
            receipts_by_record[receipt.knowledge_record_digest] = receipt

        grouped: dict[str, list[GenerationKnowledge]] = {}
        seen_records = set()
        suites = set()
        for record in feedback.knowledge.records:
            if not isinstance(record, GenerationKnowledge):
                raise EvolutionPolicyError("typed authenticated GenerationKnowledge records are required")
            if (record.record_digest in seen_records or not _valid_digest(record.record_digest)
                    or not _valid_digest(record.evidence_digest)
                    or not _valid_digest(record.outcome_digest)
                    or not _valid_digest(record.candidate_artifact_digest)
                    or not _valid_digest(record.evaluation_suite_digest)):
                raise EvolutionPolicyError("knowledge record digest is invalid or replayed")
            seen_records.add(record.record_digest)
            receipt = receipts_by_record.get(record.record_digest)
            if (receipt is None or receipt.proposed_generation != record.proposed_generation
                    or receipt.knowledge_transfer_id != record.transfer_id
                    or receipt.source_outcome_digest != record.outcome_digest):
                raise EvolutionPolicyError("Stage 161 receipt does not bind to exact Stage 156 knowledge")
            if (record.pending_human_approval is not True or record.generation_advanced is not False
                    or record.model_activated is not False or record.auto_adoption_authorized is not False
                    or record.production_switch_authorized is not False):
                raise EvolutionPolicyError("knowledge record has forbidden authority state")
            if record.evaluation_suite_digest != expected_suite_digest:
                raise EvolutionPolicyError("evaluation suite drift prevents historical comparison")
            if record.strategy not in _ALLOWED_STRATEGIES:
                raise EvolutionPolicyError("unknown strategy label in authenticated knowledge")
            metrics = (record.fitness.accuracy, record.fitness.instruction_following,
                       record.fitness.safety, record.fitness.latency_ms, record.fitness.memory_mb)
            if (record.fitness.evaluation_suite_digest != expected_suite_digest
                    or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in metrics)
                    or not 0 <= record.fitness.accuracy <= 1
                    or not 0 <= record.fitness.instruction_following <= 1
                    or not 0 <= record.fitness.safety <= 1
                    or record.fitness.latency_ms <= 0 or record.fitness.memory_mb <= 0
                    or record.fitness.regression_count != 0):
                raise EvolutionPolicyError("authenticated fitness is invalid or incomparable")
            suites.add(record.evaluation_suite_digest)
            grouped.setdefault(record.strategy, []).append(record)
        if set(receipts_by_record) != seen_records or len(suites) != 1:
            raise EvolutionPolicyError("receipt set or frozen evaluation suite is inconsistent")

        learnings = []
        for strategy, records in sorted(grouped.items()):
            records.sort(key=lambda x: (x.proposed_generation, x.record_digest))
            if any(records[i].proposed_generation <= records[i - 1].proposed_generation for i in range(1, len(records))):
                raise EvolutionPolicyError("strategy history must have strictly increasing generations")
            count = len(records)
            quality_values = [(x.fitness.accuracy + x.fitness.instruction_following) / 2 for x in records]
            safety_values = [x.fitness.safety for x in records]
            latency_values = [x.fitness.latency_ms for x in records]
            memory_values = [x.fitness.memory_mb for x in records]
            quality_mean = sum(quality_values) / count
            safety_mean = sum(safety_values) / count
            latency_mean = sum(latency_values) / count
            memory_mean = sum(memory_values) / count
            # Confidence grows slowly with independent historical outcomes and is
            # capped; one lucky experiment can never dominate a new tournament.
            confidence = min(1.0, count / 5.0)
            safety_factor = max(0.0, min(1.0, (safety_mean - 0.95) / 0.05))
            resource_factor = 1.0 / (1.0 + latency_mean / 10000.0 + memory_mean / 10000.0)
            raw_score = (quality_mean * 0.7 + safety_factor * 0.2 + resource_factor * 0.1)
            prior = max(-0.15, min(0.15, (raw_score - 0.5) * confidence * 0.3))
            learnings.append(StrategyLearning(
                strategy, count, count, quality_mean, safety_mean,
                latency_mean, memory_mean, confidence, prior,
                tuple(x.record_digest for x in records),
            ))

        payload = {
            "feedback": feedback.digest,
            "suite": expected_suite_digest,
            "learnings": [{
                "strategy": x.strategy, "count": x.observations,
                "improved": x.improved_observations, "quality": x.quality_mean,
                "safety": x.safety_mean, "latency": x.latency_mean_ms,
                "memory": x.memory_mean_mb, "confidence": x.confidence,
                "prior": x.prior_score, "records": list(x.evidence_record_digests),
            } for x in learnings],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return EvolutionarySelectionPolicy(feedback.digest, expected_suite_digest, tuple(learnings), digest)


class EvolutionaryTournamentPolicyAdvisor:
    """Applies a tiny prior as a tie-break adjustment without altering tournament scores."""

    def rank(
        self,
        tournament: MergeTournamentReport,
        policy: EvolutionarySelectionPolicy,
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> StrategyRankingAdvice:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionPolicyError("HOLD, kill switch, or unavailable budget blocks ranking advice")
        if not isinstance(tournament, MergeTournamentReport) or not isinstance(policy, EvolutionarySelectionPolicy):
            raise EvolutionPolicyError("typed Stage 158 tournament and Stage 162 policy are required")
        if (not tournament.proposal_only or tournament.execution_authorized
                or tournament.merge_authorized or tournament.weight_mutation_authorized
                or tournament.generation_advanced or tournament.model_activated
                or tournament.production_switch_authorized):
            raise EvolutionPolicyError("tournament contains forbidden authority")
        if (not policy.proposal_only or policy.selection_authorized or policy.execution_authorized
                or policy.model_mutation_authorized or policy.model_activated):
            raise EvolutionPolicyError("selection policy contains forbidden authority")
        if (not _valid_digest(tournament.digest) or not _valid_digest(policy.policy_digest)
                or tournament.evaluation_suite_digest != policy.evaluation_suite_digest):
            raise EvolutionPolicyError("tournament and learned policy are not bound to the same frozen suite")
        priors = {x.strategy: x.prior_score for x in policy.learnings}
        if any(not math.isfinite(v) or abs(v) > policy.max_prior_influence for v in priors.values()):
            raise EvolutionPolicyError("learned strategy prior exceeds its bounded influence")
        score_by_key = {(x.candidate_id, x.strategy): x for x in tournament.scores}
        if len(score_by_key) != len(tournament.scores):
            raise EvolutionPolicyError("duplicate strategy score in tournament")
        adjustments = []
        ranked = []
        for candidate_id, strategy in tournament.proposed_preferences:
            score = score_by_key.get((candidate_id, strategy))
            if score is None or not score.pareto_optimal or not score.repeatable:
                continue
            # Historical priors only order already Pareto-eligible options. They
            # cannot make a dominated, unsafe, or unrepeatable candidate eligible.
            adjustment = priors.get(strategy, 0.0)
            adjustments.append((candidate_id, strategy, adjustment))
            ranked.append((adjustment, candidate_id, strategy))
        ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
        ordered = tuple((candidate_id, strategy) for _, candidate_id, strategy in ranked)
        payload = {
            "tournament": tournament.digest, "policy": policy.policy_digest,
            "ordered": ordered, "adjustments": adjustments,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return StrategyRankingAdvice(tournament.digest, policy.policy_digest, ordered, tuple(adjustments), digest)


__all__ = [
    "EvolutionPolicyError", "StrategyLearning", "EvolutionarySelectionPolicy",
    "StrategyRankingAdvice", "EvolutionarySelectionPolicyLearner",
    "EvolutionaryTournamentPolicyAdvisor",
]
