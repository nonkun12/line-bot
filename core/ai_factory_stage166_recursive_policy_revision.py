"""Stage 166: recursive revision of evolutionary strategy policy.

Uses Stage 165's independently verified wins and failures to revise Stage 162
priors and reorder only already Pareto-eligible, repeatable Stage 158 candidates.
The output is a proposal; it cannot select, execute, merge, or activate a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

from .ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport
from .ai_factory_stage162_evolutionary_policy_learning import EvolutionarySelectionPolicy
from .ai_factory_stage165_recursive_evolution_feedback import RecursiveEvolutionFeedbackSnapshot

_HEX = re.compile(r"[0-9a-f]{64}")
_ALLOWED = {"slerp", "ties", "dare", "task_arithmetic", "lora",
            "parameter_merge", "multi_model_orchestration"}


class RecursivePolicyRevisionError(ValueError):
    """Raised when recursive policy evidence is incomplete or unsafe."""


@dataclass(frozen=True)
class RevisedStrategyPrior:
    strategy: str
    previous_prior: float
    revised_prior: float
    observations: int
    improved: int
    regressed: int
    safety_failures: int
    stagnant: int
    confidence: float
    candidate_retention_eligible: bool


@dataclass(frozen=True)
class NextGenerationCandidate:
    candidate_id: str
    strategy: str
    revised_prior: float
    pareto_eligible: bool
    repeatable: bool
    evidence_score_digest: str


@dataclass(frozen=True)
class RecursivePolicyRevisionReport:
    source_policy_digest: str
    feedback_snapshot_digest: str
    tournament_digest: str
    evaluation_suite_digest: str
    source_generation: int
    proposed_generation: int
    revised_priors: tuple[RevisedStrategyPrior, ...]
    next_generation_candidates: tuple[NextGenerationCandidate, ...]
    exploration_guidance: tuple[str, ...]
    digest: str
    proposal_only: bool = True
    candidate_selection_authorized: bool = False
    experiment_execution_authorized: bool = False
    model_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


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
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


class RecursiveEvolutionPolicyReviser:
    """Conservatively folds Stage 165 trial outcomes into Stage 162 strategy priors."""

    def revise(
        self,
        policy: EvolutionarySelectionPolicy,
        feedback: RecursiveEvolutionFeedbackSnapshot,
        tournament: MergeTournamentReport,
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_prior_delta: float = 0.05,
        max_candidates: int = 32,
    ) -> RecursivePolicyRevisionReport:
        if hold_active or kill_switch_active or not budget_available:
            raise RecursivePolicyRevisionError("HOLD, kill switch, or unavailable budget blocks policy revision")
        if not isinstance(policy, EvolutionarySelectionPolicy) or not isinstance(feedback, RecursiveEvolutionFeedbackSnapshot):
            raise RecursivePolicyRevisionError("typed Stage 162 policy and Stage 165 feedback snapshot are required")
        if not isinstance(tournament, MergeTournamentReport):
            raise RecursivePolicyRevisionError("typed Stage 158 tournament report is required")
        if (policy.proposal_only is not True or policy.selection_authorized
                or policy.execution_authorized or policy.model_mutation_authorized or policy.model_activated):
            raise RecursivePolicyRevisionError("Stage 162 policy contains forbidden authority")
        if (feedback.proposal_only is not True or feedback.generation_advanced
                or feedback.model_activated or feedback.model_mutation_authorized
                or feedback.production_switch_authorized):
            raise RecursivePolicyRevisionError("Stage 165 feedback contains forbidden authority")
        if (not tournament.proposal_only or tournament.execution_authorized
                or tournament.merge_authorized or tournament.weight_mutation_authorized
                or tournament.generation_advanced or tournament.model_activated
                or tournament.production_switch_authorized):
            raise RecursivePolicyRevisionError("Stage 158 tournament contains forbidden authority")
        digests = (policy.policy_digest, feedback.digest, tournament.digest,
                   policy.evaluation_suite_digest, feedback.evaluation_suite_digest,
                   tournament.evaluation_suite_digest)
        if not all(_valid_digest(x) for x in digests):
            raise RecursivePolicyRevisionError("source digest or evaluation-suite digest is invalid")
        if len({policy.evaluation_suite_digest, feedback.evaluation_suite_digest,
                tournament.evaluation_suite_digest}) != 1:
            raise RecursivePolicyRevisionError("frozen evaluation suite drift prevents recursive revision")
        if _snapshot_digest(feedback) != feedback.digest:
            raise RecursivePolicyRevisionError("Stage 165 snapshot digest does not match its contents")
        if (not isinstance(max_prior_delta, (int, float)) or isinstance(max_prior_delta, bool)
                or not math.isfinite(max_prior_delta) or not 0 < max_prior_delta <= 0.05):
            raise RecursivePolicyRevisionError("max_prior_delta must be in (0, 0.05]")
        if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or not 1 <= max_candidates <= 64:
            raise RecursivePolicyRevisionError("max_candidates must be between 1 and 64")
        if len(feedback.records) > 4096 or len(feedback.summaries) > 64:
            raise RecursivePolicyRevisionError("Stage 165 feedback exceeds revision capacity")

        record_digests, outcome_digests = set(), set()
        grouped = {}
        generations = set()
        for record in feedback.records:
            if (not _valid_digest(record.record_digest) or not _valid_digest(record.outcome_digest)
                    or not _valid_digest(record.evidence_digest) or not _valid_digest(record.design_digest)
                    or not _valid_digest(record.recipe_digest)
                    or record.record_digest in record_digests or record.outcome_digest in outcome_digests):
                raise RecursivePolicyRevisionError("Stage 165 record identity is invalid or replayed")
            if (record.pending_human_approval is not True or record.generation_advanced
                    or record.model_activated or record.model_mutation_authorized
                    or record.production_switch_authorized):
                raise RecursivePolicyRevisionError("Stage 165 record contains forbidden authority")
            if record.strategy not in _ALLOWED or record.classification not in {
                "IMPROVED", "REGRESSED", "SAFETY_FAILURE", "STAGNANT"
            }:
                raise RecursivePolicyRevisionError("unknown strategy or trial classification")
            if record.proposed_generation != record.source_generation + 1 or record.source_generation < 0:
                raise RecursivePolicyRevisionError("trial generation lineage is not adjacent")
            metrics = dict(record.metrics)
            baseline = dict(record.baseline_metrics)
            expected_metrics = {"accuracy", "instruction_following", "safety", "latency_ms", "memory_mb", "regression_count"}
            if set(metrics) != expected_metrics or set(baseline) != expected_metrics:
                raise RecursivePolicyRevisionError("trial metric set is incomplete")
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
                   for v in (*metrics.values(), *baseline.values())):
                raise RecursivePolicyRevisionError("trial metrics must be finite")
            if not 0 <= metrics["safety"] <= 1 or metrics["latency_ms"] <= 0 or metrics["memory_mb"] <= 0:
                raise RecursivePolicyRevisionError("trial safety or resource metrics are invalid")
            record_digests.add(record.record_digest)
            outcome_digests.add(record.outcome_digest)
            generations.add(record.source_generation)
            grouped.setdefault(record.strategy, []).append(record)

        if feedback.records and len(generations) != 1:
            raise RecursivePolicyRevisionError("one recursive revision must use a single source generation")
        summaries = {x.strategy: x for x in feedback.summaries}
        if len(summaries) != len(feedback.summaries) or set(summaries) != set(grouped):
            raise RecursivePolicyRevisionError("Stage 165 strategy summaries do not match trial records")
        for strategy, records in grouped.items():
            summary = summaries[strategy]
            counts = {
                "observations": len(records),
                "improved": sum(x.classification == "IMPROVED" for x in records),
                "regressed": sum(x.classification == "REGRESSED" for x in records),
                "safety_failures": sum(x.classification == "SAFETY_FAILURE" for x in records),
                "stagnant": sum(x.classification == "STAGNANT" for x in records),
            }
            if any(getattr(summary, key) != value for key, value in counts.items()):
                raise RecursivePolicyRevisionError("Stage 165 summary counters do not match its records")

        prior_by_strategy = {}
        for learning in policy.learnings:
            if learning.strategy in prior_by_strategy or learning.strategy not in _ALLOWED:
                raise RecursivePolicyRevisionError("duplicate or unknown Stage 162 strategy prior")
            if (not isinstance(learning.prior_score, (int, float)) or isinstance(learning.prior_score, bool)
                    or not math.isfinite(learning.prior_score)
                    or abs(learning.prior_score) > policy.max_prior_influence):
                raise RecursivePolicyRevisionError("Stage 162 prior exceeds its bounded influence")
            prior_by_strategy[learning.strategy] = learning.prior_score

        revisions = []
        for strategy in sorted(set(prior_by_strategy) | set(grouped)):
            previous = float(prior_by_strategy.get(strategy, 0.0))
            records = grouped.get(strategy, [])
            improved = sum(x.classification == "IMPROVED" for x in records)
            regressed = sum(x.classification == "REGRESSED" for x in records)
            safety = sum(x.classification == "SAFETY_FAILURE" for x in records)
            stagnant = sum(x.classification == "STAGNANT" for x in records)
            count = len(records)
            # Small bounded updates: failures carry stronger penalties than a single win.
            raw_delta = 0.0
            if count:
                raw_delta = 0.01 * improved - 0.02 * regressed - 0.05 * safety - 0.01 * stagnant
                raw_delta *= min(1.0, count / 3.0)
            delta = max(-max_prior_delta, min(max_prior_delta, raw_delta))
            revised = max(-policy.max_prior_influence,
                          min(policy.max_prior_influence, previous + delta))
            confidence = min(1.0, count / 5.0)
            revisions.append(RevisedStrategyPrior(
                strategy, previous, revised, count, improved, regressed, safety,
                stagnant, confidence, bool(count and safety == 0 and regressed == 0 and improved > 0),
            ))

        revised_map = {x.strategy: x for x in revisions}
        score_by_key = {(x.candidate_id, x.strategy): x for x in tournament.scores}
        if len(score_by_key) != len(tournament.scores):
            raise RecursivePolicyRevisionError("duplicate tournament candidate/strategy score")
        if len(tournament.proposed_preferences) > max_candidates:
            raise RecursivePolicyRevisionError("tournament preferences exceed candidate capacity")
        seen_preferences = set()
        candidates = []
        for candidate_id, strategy in tournament.proposed_preferences:
            key = (candidate_id, strategy)
            score = score_by_key.get(key)
            if key in seen_preferences:
                raise RecursivePolicyRevisionError("duplicate tournament preference")
            seen_preferences.add(key)
            if score is None or not score.pareto_optimal or not score.repeatable:
                continue
            if score.median_fitness.safety < 0.95 or score.median_fitness.regression_count:
                continue
            prior = revised_map.get(strategy)
            if prior is None or not prior.candidate_retention_eligible:
                continue
            candidates.append(NextGenerationCandidate(
                candidate_id, strategy, prior.revised_prior if prior else 0.0,
                True, True, score.score_digest,
            ))
        candidates.sort(key=lambda x: (-x.revised_prior, x.candidate_id, x.strategy))

        guidance = []
        for item in revisions:
            if item.safety_failures:
                guidance.append(f"{item.strategy}: safety failure; exclude candidate retention until a fresh independent safety pass")
            if item.regressed:
                guidance.append(f"{item.strategy}: regression; focus the next experiment on failing dimensions")
            if item.stagnant:
                guidance.append(f"{item.strategy}: stagnation; allocate bounded exploration to alternative strategies or regions")
            if item.improved:
                guidance.append(f"{item.strategy}: improvement observed; require independent repeatability before selection")
        if not guidance:
            guidance.append("no verified Stage 165 trials; preserve the current policy and collect evidence")

        source_generation = max(generations) if generations else 0
        payload = {
            "policy": policy.policy_digest, "feedback": feedback.digest,
            "tournament": tournament.digest, "suite": tournament.evaluation_suite_digest,
            "source_generation": source_generation,
            "revisions": [{
                "strategy": x.strategy, "previous": x.previous_prior,
                "revised": x.revised_prior, "observations": x.observations,
                "improved": x.improved, "regressed": x.regressed,
                "safety_failures": x.safety_failures, "stagnant": x.stagnant,
                "confidence": x.confidence, "retention": x.candidate_retention_eligible,
            } for x in revisions],
            "candidates": [{
                "candidate": x.candidate_id, "strategy": x.strategy,
                "prior": x.revised_prior, "score": x.evidence_score_digest,
            } for x in candidates],
            "guidance": guidance,
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return RecursivePolicyRevisionReport(
            policy.policy_digest, feedback.digest, tournament.digest,
            tournament.evaluation_suite_digest, source_generation,
            source_generation + 1, tuple(revisions), tuple(candidates),
            tuple(guidance), digest,
        )


__all__ = [
    "RecursivePolicyRevisionError", "RevisedStrategyPrior",
    "NextGenerationCandidate", "RecursivePolicyRevisionReport",
    "RecursiveEvolutionPolicyReviser",
]
