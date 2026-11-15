"""Stage 159: evidence-bound handoff from tournament winners to isolated experiments.

This stage converts Stage 158 Pareto preferences into approval-gated experiment
proposals. It never executes a sandbox, consumes approval tokens, or mutates models.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Sequence

from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlanReport
from .ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class ExperimentHandoffError(ValueError):
    """Raised when tournament-to-experiment lineage is invalid or unsafe."""


@dataclass(frozen=True)
class ExperimentDispatchProposal:
    proposal_id: str
    candidate_id: str
    strategy: str
    plan_id: str
    generation: int
    recipe_digest: str
    candidate_artifact_digest: str
    parent_artifact_digests: tuple[str, ...]
    evaluation_suite_digest: str
    tournament_digest: str
    strategy_score_digest: str
    required_approval_scope: str
    digest: str
    proposal_only: bool = True
    approval_required: bool = True
    approval_consumed: bool = False
    execution_authorized: bool = False
    merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False


@dataclass(frozen=True)
class ExperimentHandoffReport:
    tournament_digest: str
    source_plan_digest: str
    evaluation_suite_digest: str
    proposals: tuple[ExperimentDispatchProposal, ...]
    rejected_preferences: tuple[tuple[str, str, str], ...]
    digest: str
    proposal_only: bool = True
    dispatch_performed: bool = False
    approval_consumed: bool = False
    execution_authorized: bool = False
    model_activated: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


class EvolutionaryExperimentHandoff:
    """Builds deterministic, bounded, human-approval-gated experiment proposals."""

    def __init__(self, *, max_proposals: int = 32) -> None:
        if not isinstance(max_proposals, int) or isinstance(max_proposals, bool) or not 1 <= max_proposals <= 128:
            raise ValueError("max_proposals must be between 1 and 128")
        self._max_proposals = max_proposals

    def prepare(
        self,
        *,
        plans: MergeEvaluationPlanReport,
        tournament: MergeTournamentReport,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> ExperimentHandoffReport:
        if hold_active or kill_switch_active or not budget_available:
            raise ExperimentHandoffError("HOLD, kill switch, or unavailable budget blocks experiment handoff")
        if not isinstance(plans, MergeEvaluationPlanReport) or not isinstance(tournament, MergeTournamentReport):
            raise ExperimentHandoffError("typed Stage 154 plan and Stage 158 tournament reports are required")
        if (not plans.proposal_only or not tournament.proposal_only
                or plans.tensors_read or plans.weights_modified or plans.inference_executed
                or plans.generation_advanced or plans.production_switch_authorized
                or tournament.execution_authorized or tournament.merge_authorized
                or tournament.weight_mutation_authorized or tournament.generation_advanced
                or tournament.model_activated or tournament.production_switch_authorized):
            raise ExperimentHandoffError("upstream reports contain forbidden authority or execution")
        if (not _valid_digest(plans.digest) or not _valid_digest(plans.evaluation_suite_digest)
                or not _valid_digest(tournament.digest)
                or tournament.source_plan_digest != plans.digest
                or tournament.evaluation_suite_digest != plans.evaluation_suite_digest):
            raise ExperimentHandoffError("tournament does not bind to the exact Stage 154 plan and frozen suite")
        if len(tournament.scores) > 1024 or len(tournament.proposed_preferences) > 1024:
            raise ExperimentHandoffError("upstream tournament exceeds handoff capacity")

        plans_by_key = {}
        for plan in plans.plans:
            key = (plan.candidate_id, plan.algorithm.value)
            if key in plans_by_key:
                raise ExperimentHandoffError("ambiguous duplicate candidate strategy plan")
            plans_by_key[key] = plan

        score_by_key = {}
        for score in tournament.scores:
            key = (score.candidate_id, score.strategy)
            if key in score_by_key:
                raise ExperimentHandoffError("duplicate candidate strategy score")
            if not _valid_digest(score.score_digest):
                raise ExperimentHandoffError("strategy score digest is invalid")
            score_by_key[key] = score

        proposals = []
        rejected = []
        seen = set()
        for candidate_id, strategy in sorted(tournament.proposed_preferences):
            key = (candidate_id, strategy)
            if key in seen:
                raise ExperimentHandoffError("duplicate Pareto preference")
            seen.add(key)
            score = score_by_key.get(key)
            plan = plans_by_key.get(key)
            if score is None or plan is None:
                # Orchestration routes and parameter plans have distinct execution
                # semantics. Stage 159 deliberately hands off only real merge plans.
                rejected.append((candidate_id, strategy, "no executable Stage 154 parameter plan"))
                continue
            if (not score.pareto_optimal or not score.repeatable
                    or score.median_fitness.safety < 0.95
                    or score.median_fitness.regression_count != 0
                    or score.trial_count < 2):
                rejected.append((candidate_id, strategy, "score is not repeatable and safety eligible"))
                continue
            if (plan.execution_authorized or plan.merge_authorized or plan.activation_authorized
                    or not plan.independent_evaluation_required):
                raise ExperimentHandoffError("Stage 154 plan has invalid authority or evaluation requirements")
            if (not _valid_digest(plan.recipe_digest)
                    or not _valid_digest(plan.candidate_artifact_digest)
                    or any(not _valid_digest(x) for x in plan.parent_artifact_digests)
                    or plan.evaluation_suite_digest != plans.evaluation_suite_digest):
                raise ExperimentHandoffError("selected plan artifact lineage or suite digest is invalid")
            if len(proposals) >= self._max_proposals:
                raise ExperimentHandoffError("experiment proposal capacity reached")
            canonical = {
                "candidate": candidate_id, "strategy": strategy, "plan": plan.plan_id,
                "generation": plan.generation, "recipe": plan.recipe_digest,
                "candidate_artifact": plan.candidate_artifact_digest,
                "parents": list(plan.parent_artifact_digests),
                "suite": plan.evaluation_suite_digest, "tournament": tournament.digest,
                "score": score.score_digest, "approval_scope": "single-plan-recipe-digest",
            }
            raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            proposal_id = hashlib.sha256(("stage159:" + digest).encode()).hexdigest()
            proposals.append(ExperimentDispatchProposal(
                proposal_id, candidate_id, strategy, plan.plan_id, plan.generation,
                plan.recipe_digest, plan.candidate_artifact_digest,
                plan.parent_artifact_digests, plan.evaluation_suite_digest,
                tournament.digest, score.score_digest, "single-plan-recipe-digest", digest,
            ))

        payload = {
            "plans": plans.digest, "tournament": tournament.digest,
            "suite": plans.evaluation_suite_digest,
            "proposals": [x.digest for x in proposals],
            "rejected": rejected,
        }
        report_digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        return ExperimentHandoffReport(
            tournament.digest, plans.digest, plans.evaluation_suite_digest,
            tuple(proposals), tuple(rejected), report_digest,
        )


__all__ = [
    "ExperimentHandoffError", "ExperimentDispatchProposal",
    "ExperimentHandoffReport", "EvolutionaryExperimentHandoff",
]
