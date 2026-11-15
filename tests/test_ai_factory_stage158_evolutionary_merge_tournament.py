from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeEvaluationPlanReport,
    MergeStrategyParameters, OrchestrationRoute,
)
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    EvolutionaryMergeTournament, MergeTournamentError, StrategyTrialEvidence,
)

SUITE = "a" * 64
ARTIFACT = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64


def plan(algorithm=MergeAlgorithm.SLERP, plan_id="plan-slerp"):
    return MergeEvaluationPlan(
        plan_id=plan_id, candidate_id="candidate-1", generation=4,
        algorithm=algorithm,
        parameters=(MergeStrategyParameters(interpolation=.5) if algorithm is MergeAlgorithm.SLERP
                    else MergeStrategyParameters(density=.8, merge_coefficient=1.0)),
        parent_model_ids=("parent-a", "parent-b"),
        parent_artifact_digests=(PARENT_A, PARENT_B),
        candidate_artifact_digest=ARTIFACT, evaluation_suite_digest=SUITE,
        recipe_digest=("e" if algorithm is MergeAlgorithm.SLERP else "f") * 64,
        strategy="parameter_merge",
    )


def report(plans=None, routes=()):
    items = tuple(plans or (plan(), plan(MergeAlgorithm.TIES, "plan-ties")))
    return MergeEvaluationPlanReport(SUITE, "9" * 64, items, tuple(routes), "8" * 64)


def fitness(accuracy=.90, instruction=.90, safety=.99, latency=100, memory=500, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def trial(p, replicate, *, evaluator=None, metrics=None, **changes):
    item = StrategyTrialEvidence(
        trial_id=f"{p.plan_id}-trial-{replicate}",
        plan_id=p.plan_id, candidate_id=p.candidate_id, generation=p.generation,
        strategy=p.algorithm.value, parent_model_ids=p.parent_model_ids,
        parent_artifact_digests=p.parent_artifact_digests,
        candidate_artifact_digest=p.candidate_artifact_digest,
        evaluation_suite_digest=SUITE, replicate=replicate,
        evaluator_id=evaluator or f"evaluator-{p.plan_id}-{replicate}",
        evidence_digest=(format(replicate + (1 if p.algorithm is MergeAlgorithm.SLERP else 10), "064x")),
        fitness=metrics or fitness(), signature="a" * 64,
    )
    return replace(item, **changes)


def verify(_):
    return True


def test_repeated_comparable_trials_produce_deterministic_pareto_preferences():
    r = report()
    slerp, ties = r.plans
    trials = [
        trial(slerp, 1, metrics=fitness(.93, .92, .99, 95, 480)),
        trial(slerp, 2, metrics=fitness(.931, .921, .991, 94, 479)),
        trial(ties, 1, metrics=fitness(.90, .90, .99, 100, 500)),
        trial(ties, 2, metrics=fitness(.901, .901, .991, 99, 499)),
    ]
    tournament = EvolutionaryMergeTournament(min_repeats=2)
    result = tournament.evaluate(r, trials, verify_trial=verify)
    assert result.proposal_only is True
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.weight_mutation_authorized is False
    assert result.generation_advanced is False
    assert result.model_activated is False
    assert result.proposed_preferences == (("candidate-1", "slerp"),)
    assert tournament.evaluate(r, trials, verify_trial=verify).digest == result.digest


def test_repeated_trials_require_distinct_evaluators_and_are_repeatable():
    r = report((plan(),))
    p = r.plans[0]
    items = [trial(p, 1), trial(p, 2, evaluator="evaluator-plan-slerp-1")]
    with pytest.raises(MergeTournamentError, match="distinct independent"):
        EvolutionaryMergeTournament().evaluate(r, items, verify_trial=verify)

    noisy = [trial(p, 1), trial(p, 2, metrics=fitness(.99, .90, .99, 100, 500))]
    result = EvolutionaryMergeTournament().evaluate(r, noisy, verify_trial=verify)
    assert result.scores[0].repeatable is False
    assert result.proposed_preferences == ()


def test_rejects_suite_drift_replay_and_invalid_signature():
    r = report((plan(),))
    p = r.plans[0]
    with pytest.raises(MergeTournamentError, match="suite drift"):
        EvolutionaryMergeTournament().evaluate(
            r, [trial(p, 1, evaluation_suite_digest="f" * 64)], verify_trial=verify
        )
    with pytest.raises(MergeTournamentError, match="duplicate"):
        EvolutionaryMergeTournament().evaluate(r, [trial(p, 1), trial(p, 1)], verify_trial=verify)
    with pytest.raises(MergeTournamentError, match="signature"):
        EvolutionaryMergeTournament().evaluate(r, [trial(p, 1)], verify_trial=lambda _: False)


def test_rejects_cross_lineage_replicates_and_duplicate_replicate_numbers():
    r = report((plan(),))
    p = r.plans[0]
    changed = replace(trial(p, 2), parent_artifact_digests=("f" * 64, PARENT_B))
    with pytest.raises(MergeTournamentError, match="exact Stage 154"):
        EvolutionaryMergeTournament().evaluate(r, [trial(p, 1), changed], verify_trial=verify)
    duplicate_replicate = replace(trial(p, 2), replicate=1)
    with pytest.raises(MergeTournamentError, match="replicate"):
        EvolutionaryMergeTournament().evaluate(r, [trial(p, 1), duplicate_replicate], verify_trial=verify)


def test_safety_regression_trials_never_become_preferred():
    r = report((plan(),))
    p = r.plans[0]
    result = EvolutionaryMergeTournament().evaluate(
        r, [trial(p, 1, metrics=fitness(safety=.94)), trial(p, 2, metrics=fitness(safety=.94))],
        verify_trial=verify,
    )
    assert result.proposed_preferences == ()
    assert result.scores[0].repeatable is False


def test_rejects_unknown_plan_and_changed_plan_lineage():
    r = report((plan(),))
    p = r.plans[0]
    with pytest.raises(MergeTournamentError, match="exact Stage 154"):
        EvolutionaryMergeTournament().evaluate(
            r, [replace(trial(p, 1), candidate_artifact_digest="f" * 64)], verify_trial=verify
        )
    with pytest.raises(MergeTournamentError, match="unknown plan"):
        EvolutionaryMergeTournament().evaluate(
            r, [replace(trial(p, 1), plan_id="not-a-plan")], verify_trial=verify
        )


def test_orchestration_route_is_scored_without_weight_merge():
    route = OrchestrationRoute("candidate-orch", ("architecture mismatch",))
    r = report((), (route,))
    make = lambda n: StrategyTrialEvidence(
        trial_id=f"orch-{n}", plan_id="orchestration:candidate-orch",
        candidate_id="candidate-orch", generation=2, strategy="multi_model_orchestration",
        parent_model_ids=(), parent_artifact_digests=(), candidate_artifact_digest=ARTIFACT,
        evaluation_suite_digest=SUITE, replicate=n, evaluator_id=f"orch-evaluator-{n}",
        evidence_digest=format(30 + n, "064x"), fitness=fitness(), signature="a" * 64,
    )
    result = EvolutionaryMergeTournament().evaluate(r, [make(1), make(2)], verify_trial=verify)
    assert result.proposed_preferences == (("candidate-orch", "multi_model_orchestration"),)
    assert result.merge_authorized is False


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_hold_kill_switch_and_budget_fail_closed(flags):
    r = report((plan(),))
    p = r.plans[0]
    with pytest.raises(MergeTournamentError):
        EvolutionaryMergeTournament().evaluate(
            r, [trial(p, 1), trial(p, 2)], verify_trial=verify, **flags
        )


def test_trial_capacity_and_repeat_count_are_bounded():
    r = report((plan(),))
    p = r.plans[0]
    with pytest.raises(MergeTournamentError, match="capacity"):
        EvolutionaryMergeTournament(max_trials=2).evaluate(
            r, [trial(p, 1), trial(p, 2), trial(p, 3)], verify_trial=verify
        )
    result = EvolutionaryMergeTournament().evaluate(r, [trial(p, 1)], verify_trial=verify)
    assert result.scores == ()
    assert result.rejected_trial_digests == (format(2, "064x"),)
