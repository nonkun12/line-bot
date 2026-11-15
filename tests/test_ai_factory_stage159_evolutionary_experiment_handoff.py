from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeEvaluationPlanReport, MergeStrategyParameters,
)
from core.ai_factory_stage158_evolutionary_merge_tournament import MergeTournamentReport, StrategyScore
from core.ai_factory_stage159_evolutionary_experiment_handoff import (
    EvolutionaryExperimentHandoff, ExperimentHandoffError,
)

SUITE = "a" * 64
ARTIFACT = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64


def make_reports():
    plan = MergeEvaluationPlan(
        plan_id="plan-slerp", candidate_id="candidate-1", generation=5,
        algorithm=MergeAlgorithm.SLERP,
        parameters=MergeStrategyParameters(interpolation=.5),
        parent_model_ids=("parent-a", "parent-b"),
        parent_artifact_digests=(PARENT_A, PARENT_B),
        candidate_artifact_digest=ARTIFACT, evaluation_suite_digest=SUITE,
        recipe_digest="e" * 64, strategy="parameter_merge",
    )
    plans = MergeEvaluationPlanReport(SUITE, "9" * 64, (plan,), (), "8" * 64)
    fitness = Fitness(.93, .92, .99, 95, 480, 0, SUITE)
    score = StrategyScore("candidate-1", "slerp", 2, ("evaluator-a", "evaluator-b"),
                          fitness, True, (), True, "f" * 64)
    tournament = MergeTournamentReport(
        plans.digest, SUITE, (score,), (("candidate-1", "slerp"),), (), "7" * 64,
    )
    return plans, tournament


def test_pareto_winner_becomes_digest_bound_approval_gated_proposal():
    plans, tournament = make_reports()
    result = EvolutionaryExperimentHandoff().prepare(plans=plans, tournament=tournament)
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.plan_id == "plan-slerp"
    assert proposal.recipe_digest == "e" * 64
    assert proposal.parent_artifact_digests == (PARENT_A, PARENT_B)
    assert proposal.approval_required is True
    assert proposal.approval_consumed is False
    assert proposal.execution_authorized is False
    assert proposal.merge_authorized is False
    assert proposal.weight_mutation_authorized is False
    assert proposal.generation_advanced is False
    assert proposal.model_activated is False
    assert result.dispatch_performed is False
    assert result.digest == EvolutionaryExperimentHandoff().prepare(
        plans=plans, tournament=tournament
    ).digest


def test_rejects_wrong_plan_or_suite_lineage():
    plans, tournament = make_reports()
    with pytest.raises(ExperimentHandoffError, match="exact Stage 154"):
        EvolutionaryExperimentHandoff().prepare(
            plans=plans, tournament=replace(tournament, source_plan_digest="0" * 64)
        )
    with pytest.raises(ExperimentHandoffError, match="exact Stage 154"):
        EvolutionaryExperimentHandoff().prepare(
            plans=plans, tournament=replace(tournament, evaluation_suite_digest="1" * 64)
        )


def test_rejects_nonrepeatable_or_unsafe_winner():
    plans, tournament = make_reports()
    unsafe = replace(tournament.scores[0], repeatable=False)
    result = EvolutionaryExperimentHandoff().prepare(
        plans=plans, tournament=replace(tournament, scores=(unsafe,))
    )
    assert result.proposals == ()
    assert result.rejected_preferences[0][2] == "score is not repeatable and safety eligible"


def test_orchestration_preference_is_not_misrouted_to_weight_merge():
    plans, tournament = make_reports()
    result = EvolutionaryExperimentHandoff().prepare(
        plans=plans,
        tournament=replace(tournament, proposed_preferences=(
            ("candidate-1", "multi_model_orchestration"),
        )),
    )
    assert result.proposals == ()
    assert result.rejected_preferences == ((
        "candidate-1", "multi_model_orchestration",
        "no executable Stage 154 parameter plan",
    ),)


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_hold_kill_switch_and_budget_fail_closed(flags):
    plans, tournament = make_reports()
    with pytest.raises(ExperimentHandoffError):
        EvolutionaryExperimentHandoff().prepare(plans=plans, tournament=tournament, **flags)


def test_rejects_upstream_authority_and_duplicate_preferences():
    plans, tournament = make_reports()
    with pytest.raises(ExperimentHandoffError, match="authority"):
        EvolutionaryExperimentHandoff().prepare(
            plans=plans, tournament=replace(tournament, merge_authorized=True)
        )
    with pytest.raises(ExperimentHandoffError, match="duplicate Pareto preference"):
        EvolutionaryExperimentHandoff().prepare(
            plans=plans,
            tournament=replace(tournament, proposed_preferences=(
                ("candidate-1", "slerp"), ("candidate-1", "slerp"),
            )),
        )
