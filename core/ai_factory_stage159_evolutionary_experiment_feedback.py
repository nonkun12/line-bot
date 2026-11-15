"""Stage 159: gated dispatch from evolutionary tournament to isolated experiments.

A Pareto-selected Stage 158 strategy can become a dispatch proposal. Actual execution
requires a separate, one-time human approval verified by the Stage 155 runner.
Verified outcomes are returned as evidence for Stage 156 knowledge transfer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage154_merge_strategy_evaluation import (
    MergeEvaluationPlan, MergeEvaluationPlanReport,
)
from .ai_factory_stage155_isolated_merge_experiments import (
    IndependentEvaluationEvidence, IndependentEvaluator, IsolatedMergeExperimentRunner,
    IsolatedSandbox, MergeExperimentOutcome, SandboxPolicy,
)
from .ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
ORCHESTRATION = "multi_model_orchestration"


class EvolutionaryDispatchError(ValueError):
    """Raised when selection, dispatch, or feedback evidence is invalid."""


@dataclass(frozen=True)
class ExperimentDispatch:
    tournament_digest: str
    source_plan_digest: str
    candidate_id: str
    strategy: str
    score_digest: str
    plan_id: str | None
    recipe_digest: str | None
    evaluation_suite_digest: str
    dispatch_digest: str
    orchestration_only: bool = False
    human_approval_required: bool = True
    execution_authorized: bool = False
    merge_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


@dataclass(frozen=True)
class EvolutionaryExperimentFeedback:
    dispatch_digest: str
    candidate_id: str
    strategy: str
    source_generation: int
    plan_id: str
    outcome: MergeExperimentOutcome
    evidence: IndependentEvaluationEvidence
    feedback_digest: str
    proposal_only: bool = True
    knowledge_transfer_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _dispatch_digest(
    tournament_digest: str, source_plan_digest: str, candidate_id: str,
    strategy: str, score_digest: str, plan_id: str | None,
    recipe_digest: str | None, suite: str, orchestration_only: bool,
) -> str:
    payload = {
        "tournament": tournament_digest, "source_plans": source_plan_digest,
        "candidate": candidate_id, "strategy": strategy, "score": score_digest,
        "plan": plan_id, "recipe": recipe_digest, "suite": suite,
        "orchestration_only": orchestration_only,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EvolutionaryExperimentFeedbackLoop:
    """Select one Pareto strategy, dispatch safely, and return signed experiment evidence."""

    def prepare_dispatch(
        self,
        tournament: MergeTournamentReport,
        plans: MergeEvaluationPlanReport,
        *,
        candidate_id: str,
        strategy: str,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> ExperimentDispatch:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionaryDispatchError("HOLD, kill switch, or unavailable budget blocks dispatch")
        if not isinstance(tournament, MergeTournamentReport) or not isinstance(plans, MergeEvaluationPlanReport):
            raise EvolutionaryDispatchError("typed Stage 158 tournament and Stage 154 plan report are required")
        if (not tournament.proposal_only or tournament.execution_authorized
                or tournament.merge_authorized or tournament.weight_mutation_authorized
                or tournament.generation_advanced or tournament.model_activated
                or tournament.production_switch_authorized):
            raise EvolutionaryDispatchError("Stage 158 tournament contains forbidden authority")
        if (not plans.proposal_only or plans.weights_modified or plans.tensors_read
                or plans.inference_executed or plans.generation_advanced
                or plans.production_switch_authorized):
            raise EvolutionaryDispatchError("Stage 154 plan report contains forbidden execution state")
        if (not _digest(tournament.digest) or not _digest(tournament.source_plan_digest)
                or not _digest(plans.digest) or not _digest(plans.evaluation_suite_digest)
                or tournament.source_plan_digest != plans.digest
                or tournament.evaluation_suite_digest != plans.evaluation_suite_digest):
            raise EvolutionaryDispatchError("tournament and frozen source plan bindings do not match")
        if not _ID.fullmatch(candidate_id or "") or not isinstance(strategy, str) or not strategy:
            raise EvolutionaryDispatchError("candidate and strategy identity are invalid")
        matches = [x for x in tournament.scores
                   if x.candidate_id == candidate_id and x.strategy == strategy]
        if len(matches) != 1:
            raise EvolutionaryDispatchError("exactly one tournament score must match the requested strategy")
        score: StrategyScore = matches[0]
        if (not score.pareto_optimal or not score.repeatable or score.trial_count < 2
                or score.median_fitness.safety < 0.95 or score.median_fitness.regression_count != 0
                or not _digest(score.score_digest)):
            raise EvolutionaryDispatchError("only repeatable, safe Pareto-selected strategies may be dispatched")

        plan_matches = [x for x in plans.plans if x.candidate_id == candidate_id
                        and x.algorithm.value == strategy]
        orchestration = strategy == ORCHESTRATION
        if orchestration:
            routes = [x for x in plans.orchestration_routes if x.candidate_id == candidate_id]
            if len(routes) != 1 or plan_matches:
                raise EvolutionaryDispatchError("orchestration route must be explicit and must not include weight plans")
            plan_id, recipe = None, None
        else:
            if len(plan_matches) != 1:
                raise EvolutionaryDispatchError("selected strategy must bind to exactly one Stage 154 merge plan")
            plan = plan_matches[0]
            if (plan.evaluation_suite_digest != tournament.evaluation_suite_digest
                    or plan.execution_authorized or plan.merge_authorized or plan.activation_authorized
                    or not plan.independent_evaluation_required
                    or not _digest(plan.recipe_digest)):
                raise EvolutionaryDispatchError("selected merge plan is unsafe or not bound to frozen suite")
            plan_id, recipe = plan.plan_id, plan.recipe_digest
        dispatch_digest = _dispatch_digest(
            tournament.digest, plans.digest, candidate_id, strategy,
            score.score_digest, plan_id, recipe, plans.evaluation_suite_digest, orchestration,
        )
        return ExperimentDispatch(
            tournament.digest, plans.digest, candidate_id, strategy, score.score_digest,
            plan_id, recipe, plans.evaluation_suite_digest, dispatch_digest,
            orchestration_only=orchestration,
        )

    def execute_approved(
        self,
        dispatch: ExperimentDispatch,
        plans: MergeEvaluationPlanReport,
        *,
        approval_token: str,
        verify_approval: Callable[[str, str], bool],
        sandbox: IsolatedSandbox,
        evaluator: IndependentEvaluator,
        verify_evaluation_evidence: Callable[[IndependentEvaluationEvidence], bool],
        baseline_fitness: Fitness,
        runner: IsolatedMergeExperimentRunner | None = None,
        policy: SandboxPolicy = SandboxPolicy(),
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionaryExperimentFeedback:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionaryDispatchError("HOLD, kill switch, or unavailable budget blocks experiment execution")
        if not isinstance(dispatch, ExperimentDispatch) or not isinstance(plans, MergeEvaluationPlanReport):
            raise EvolutionaryDispatchError("typed dispatch and source plan report are required")
        if dispatch.orchestration_only:
            raise EvolutionaryDispatchError("orchestration route cannot invoke parameter-merge sandbox")
        if (dispatch.execution_authorized or dispatch.merge_authorized
                or dispatch.generation_advanced or dispatch.model_activated
                or dispatch.production_switch_authorized or not dispatch.human_approval_required):
            raise EvolutionaryDispatchError("dispatch authority flags are invalid")
        expected = _dispatch_digest(
            dispatch.tournament_digest, dispatch.source_plan_digest, dispatch.candidate_id,
            dispatch.strategy, dispatch.score_digest, dispatch.plan_id, dispatch.recipe_digest,
            dispatch.evaluation_suite_digest, dispatch.orchestration_only,
        )
        if (dispatch.dispatch_digest != expected or dispatch.source_plan_digest != plans.digest
                or dispatch.evaluation_suite_digest != plans.evaluation_suite_digest):
            raise EvolutionaryDispatchError("dispatch digest or source plan binding mismatch")
        plan_matches = [x for x in plans.plans if x.plan_id == dispatch.plan_id]
        if len(plan_matches) != 1:
            raise EvolutionaryDispatchError("dispatch must resolve to exactly one immutable Stage 154 plan")
        plan: MergeEvaluationPlan = plan_matches[0]
        if (plan.candidate_id != dispatch.candidate_id or plan.algorithm.value != dispatch.strategy
                or plan.recipe_digest != dispatch.recipe_digest
                or plan.evaluation_suite_digest != dispatch.evaluation_suite_digest):
            raise EvolutionaryDispatchError("dispatch does not bind to the selected exact plan")
        experiment_runner = runner or IsolatedMergeExperimentRunner()
        captured_evidence: list[IndependentEvaluationEvidence] = []
        try:
            outcome = experiment_runner.run(
                plan=plan, approval_token=approval_token, verify_approval=verify_approval,
                sandbox=sandbox, evaluator=evaluator,
                verify_evaluation_evidence=verify_evaluation_evidence,
                baseline_fitness=baseline_fitness, policy=policy,
                evidence_sink=captured_evidence.append,
            )
        except Exception as exc:
            raise EvolutionaryDispatchError("Stage 155 isolated experiment did not produce verified feedback") from exc
        if not isinstance(outcome, MergeExperimentOutcome):
            raise EvolutionaryDispatchError("Stage 155 runner returned an untyped outcome")
        if (outcome.plan_id != plan.plan_id or outcome.recipe_digest != plan.recipe_digest
                or not outcome.proposal_only or outcome.generation_advanced
                or outcome.model_activated or outcome.production_switch_authorized):
            raise EvolutionaryDispatchError("Stage 155 outcome identity or authority is invalid")
        if len(captured_evidence) != 1:
            raise EvolutionaryDispatchError("Stage 155 must return exactly one verified evidence envelope")
        evidence = captured_evidence[0]
        if not isinstance(evidence, IndependentEvaluationEvidence):
            raise EvolutionaryDispatchError("verified Stage 155 evidence envelope is required for feedback transfer")
        if (evidence.evidence_digest != outcome.evaluation_evidence_digest
                or evidence.artifact_digest != outcome.output_artifact_digest
                or evidence.evaluator_id != outcome.evaluator_id
                or evidence.evaluation_suite_digest != plan.evaluation_suite_digest):
            raise EvolutionaryDispatchError("Stage 155 outcome and evidence envelope mismatch")
        payload = {
            "dispatch": dispatch.dispatch_digest, "candidate": plan.candidate_id,
            "strategy": dispatch.strategy, "generation": plan.generation,
            "plan": plan.plan_id, "outcome": outcome.outcome_digest,
            "evidence": evidence.evidence_digest, "artifact": evidence.artifact_digest,
        }
        feedback_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return EvolutionaryExperimentFeedback(
            dispatch.dispatch_digest, plan.candidate_id, dispatch.strategy, plan.generation,
            plan.plan_id, outcome, evidence, feedback_digest,
        )


__all__ = [
    "EvolutionaryDispatchError", "ExperimentDispatch",
    "EvolutionaryExperimentFeedback", "EvolutionaryExperimentFeedbackLoop",
]
