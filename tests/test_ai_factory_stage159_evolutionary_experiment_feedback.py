from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeEvaluationPlanReport, MergeStrategyParameters,
)
from core.ai_factory_stage155_isolated_merge_experiments import (
    IndependentEvaluationEvidence, MergeExperimentOutcome,
)
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage159_evolutionary_experiment_feedback import (
    EvolutionaryDispatchError, EvolutionaryExperimentFeedbackLoop,
)

SUITE = "a" * 64
SOURCE = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64
CANDIDATE = "e" * 64
RECIPE = "f" * 64
EVIDENCE = "1" * 64
OUTPUT = "2" * 64
OUTCOME_DIGEST = "3" * 64


def fitness(accuracy=.92, instruction=.91, safety=.99, latency=95, memory=480):
    return Fitness(accuracy, instruction, safety, latency, memory, 0, SUITE)


def fixtures():
    plan = MergeEvaluationPlan(
        plan_id="plan-159", candidate_id="candidate-159", generation=7,
        algorithm=MergeAlgorithm.SLERP,
        parameters=MergeStrategyParameters(interpolation=.5),
        parent_model_ids=("parent-a", "parent-b"),
        parent_artifact_digests=(PARENT_A, PARENT_B),
        candidate_artifact_digest=CANDIDATE, evaluation_suite_digest=SUITE,
        recipe_digest=RECIPE, strategy="parameter_merge",
    )
    plans = MergeEvaluationPlanReport(SUITE, SOURCE, (plan,), (), "4" * 64)
    score = StrategyScore("candidate-159", "slerp", 2, ("eval-a", "eval-b"),
                           fitness(), True, (), True, "5" * 64)
    tournament = MergeTournamentReport("4" * 64, SUITE, (score,),
                                       (("candidate-159", "slerp"),), (), "6" * 64)
    evidence = IndependentEvaluationEvidence(
        "independent-evaluator", OUTPUT, SUITE, fitness(.93, .92, .99, 93, 470),
        EVIDENCE, "signed-evidence",
    )
    outcome = MergeExperimentOutcome(
        "plan-159", RECIPE, OUTPUT, EVIDENCE, "independent-evaluator",
        True, (), OUTCOME_DIGEST,
    )
    return plan, plans, tournament, evidence, outcome


class FakeRunner:
    def __init__(self, evidence, outcome):
        self.evidence, self.outcome = evidence, outcome
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        assert kwargs["approval_token"] == "human-approved-once"
        assert kwargs["verify_approval"]("human-approved-once", RECIPE)
        kwargs["evidence_sink"](self.evidence)
        return self.outcome


def test_pareto_selected_strategy_dispatches_only_with_human_approval_and_returns_evidence():
    plan, plans, tournament, evidence, outcome = fixtures()
    loop = EvolutionaryExperimentFeedbackLoop()
    dispatch = loop.prepare_dispatch(
        tournament, plans, candidate_id="candidate-159", strategy="slerp"
    )
    assert dispatch.human_approval_required is True
    assert dispatch.execution_authorized is False
    assert dispatch.merge_authorized is False

    runner = FakeRunner(evidence, outcome)
    feedback = loop.execute_approved(
        dispatch, plans, approval_token="human-approved-once",
        verify_approval=lambda token, recipe: token == "human-approved-once" and recipe == RECIPE,
        sandbox=object(), evaluator=object(), verify_evaluation_evidence=lambda _: True,
        baseline_fitness=fitness(), runner=runner,
    )
    assert runner.calls == 1
    assert feedback.outcome is outcome
    assert feedback.evidence is evidence
    assert feedback.source_generation == 7
    assert feedback.proposal_only is True
    assert feedback.knowledge_transfer_authorized is False
    assert feedback.generation_advanced is False
    assert feedback.model_activated is False


def test_non_pareto_or_unsafe_strategy_cannot_be_dispatched():
    _, plans, tournament, _, _ = fixtures()
    loop = EvolutionaryExperimentFeedbackLoop()
    with pytest.raises(EvolutionaryDispatchError, match="Pareto-selected"):
        loop.prepare_dispatch(
            replace(tournament, scores=(replace(tournament.scores[0], pareto_optimal=False),)),
            plans, candidate_id="candidate-159", strategy="slerp",
        )
    with pytest.raises(EvolutionaryDispatchError, match="Pareto-selected"):
        loop.prepare_dispatch(
            replace(tournament, scores=(replace(tournament.scores[0], repeatable=False),)),
            plans, candidate_id="candidate-159", strategy="slerp",
        )


def test_hold_kill_switch_and_budget_fail_closed():
    _, plans, tournament, _, _ = fixtures()
    loop = EvolutionaryExperimentFeedbackLoop()
    for flags in ({"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False}):
        with pytest.raises(EvolutionaryDispatchError):
            loop.prepare_dispatch(tournament, plans, candidate_id="candidate-159", strategy="slerp", **flags)


def test_rejects_digest_tampering_and_authority_flags():
    _, plans, tournament, _, _ = fixtures()
    loop = EvolutionaryExperimentFeedbackLoop()
    dispatch = loop.prepare_dispatch(tournament, plans, candidate_id="candidate-159", strategy="slerp")
    with pytest.raises(EvolutionaryDispatchError, match="digest"):
        loop.execute_approved(
            replace(dispatch, candidate_id="tampered"), plans, approval_token="x",
            verify_approval=lambda *_: True, sandbox=object(), evaluator=object(),
            verify_evaluation_evidence=lambda _: True, baseline_fitness=fitness(),
        )
    with pytest.raises(EvolutionaryDispatchError, match="authority"):
        loop.execute_approved(
            replace(dispatch, execution_authorized=True), plans, approval_token="x",
            verify_approval=lambda *_: True, sandbox=object(), evaluator=object(),
            verify_evaluation_evidence=lambda _: True, baseline_fitness=fitness(),
        )


def test_orchestration_only_never_enters_weight_merge_runner():
    _, plans, tournament, _, _ = fixtures()
    route = replace(tournament.scores[0], strategy="multi_model_orchestration")
    route_report = replace(
        tournament, scores=(route,),
        proposed_preferences=(("candidate-159", "multi_model_orchestration"),),
    )
    route_plans = replace(plans, plans=(), orchestration_routes=(
        __import__("core.ai_factory_stage154_merge_strategy_evaluation", fromlist=["OrchestrationRoute"]).OrchestrationRoute(
            "candidate-159", ("incompatible model formats",)
        ),
    ))
    loop = EvolutionaryExperimentFeedbackLoop()
    dispatch = loop.prepare_dispatch(
        route_report, route_plans, candidate_id="candidate-159",
        strategy="multi_model_orchestration",
    )
    assert dispatch.orchestration_only is True
    with pytest.raises(EvolutionaryDispatchError, match="cannot invoke"):
        loop.execute_approved(
            dispatch, route_plans, approval_token="x", verify_approval=lambda *_: True,
            sandbox=object(), evaluator=object(), verify_evaluation_evidence=lambda _: True,
            baseline_fitness=fitness(), runner=FakeRunner(None, None),
        )


def test_rejects_missing_or_mismatched_verified_evidence():
    _, plans, tournament, evidence, outcome = fixtures()
    loop = EvolutionaryExperimentFeedbackLoop()
    dispatch = loop.prepare_dispatch(tournament, plans, candidate_id="candidate-159", strategy="slerp")
    bad_evidence = replace(evidence, evidence_digest="9" * 64)
    with pytest.raises(EvolutionaryDispatchError, match="mismatch"):
        loop.execute_approved(
            dispatch, plans, approval_token="human-approved-once",
            verify_approval=lambda *_: True, sandbox=object(), evaluator=object(),
            verify_evaluation_evidence=lambda _: True, baseline_fitness=fitness(),
            runner=FakeRunner(bad_evidence, outcome),
        )


def test_rejects_invalid_tournament_source_binding():
    _, plans, tournament, _, _ = fixtures()
    with pytest.raises(EvolutionaryDispatchError, match="bindings"):
        EvolutionaryExperimentFeedbackLoop().prepare_dispatch(
            replace(tournament, source_plan_digest="9" * 64), plans,
            candidate_id="candidate-159", strategy="slerp",
        )
