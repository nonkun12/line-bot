from dataclasses import replace
import hashlib

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionarySelectionPolicy, StrategyLearning,
)
from core.ai_factory_stage163_failure_informed_exploration import (
    ExplorationPlanningError, FailureInformedExplorationPlanner,
    TournamentAttestation,
)

SUITE = "a" * 64


def make_score(strategy="slerp", *, repeatable=True, safety=.99, regressions=0, reasons=()):
    fitness = Fitness(.94, .93, safety, 80, 420, regressions, SUITE)
    return StrategyScore(
        "candidate-" + strategy, strategy, 2, ("eval-a", "eval-b"),
        fitness, repeatable, reasons, repeatable and safety >= .95 and regressions == 0,
        hashlib.sha256(strategy.encode()).hexdigest(),
    )


def make_inputs(scores=None):
    scores = scores or (
        make_score("slerp"),
        make_score("ties", repeatable=False, reasons=("accuracy variance exceeds repeatability limit",)),
        make_score("dare", safety=.90),
    )
    tournament = MergeTournamentReport(
        "b" * 64, SUITE, tuple(scores),
        tuple((x.candidate_id, x.strategy) for x in scores if x.pareto_optimal),
        ("c" * 64,), "d" * 64,
    )
    learning = StrategyLearning("slerp", 2, 2, .93, .99, 80, 420, .4, .02, ("e" * 64,))
    policy = EvolutionarySelectionPolicy("f" * 64, SUITE, (learning,), "1" * 64)
    attestation = TournamentAttestation(tournament.digest, SUITE, 4, "independent-reviewer", "signed-envelope")
    return tournament, attestation, policy


def test_failure_signals_increase_diagnostic_repeats_without_granting_authority():
    tournament, attestation, policy = make_inputs()
    plan = FailureInformedExplorationPlanner().plan(
        tournament, attestation, policy, verify_attestation=lambda report, envelope: True
    )
    profiles = {x.strategy: x for x in plan.profiles}
    assert profiles["ties"].repeatability_failures == 1
    assert profiles["ties"].recommended_repeats > profiles["slerp"].recommended_repeats
    assert profiles["dare"].safety_failures == 1
    assert profiles["dare"].retain_as_candidate is False
    assert 0 < plan.total_exploration_share <= 1
    assert plan.proposal_only is True
    assert plan.experiment_execution_authorized is False
    assert plan.model_activated is False


def test_rejects_unverified_attestation_and_suite_drift():
    tournament, attestation, policy = make_inputs()
    with pytest.raises(ExplorationPlanningError, match="attestation verification"):
        FailureInformedExplorationPlanner().plan(
            tournament, attestation, policy, verify_attestation=lambda report, envelope: False
        )
    wrong_suite = replace(policy, evaluation_suite_digest="2" * 64)
    with pytest.raises(ExplorationPlanningError, match="suite"):
        FailureInformedExplorationPlanner().plan(
            tournament, attestation, wrong_suite, verify_attestation=lambda report, envelope: True
        )


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_fails_closed_on_global_gates(flags):
    tournament, attestation, policy = make_inputs()
    with pytest.raises(ExplorationPlanningError):
        FailureInformedExplorationPlanner().plan(
            tournament, attestation, policy,
            verify_attestation=lambda report, envelope: True, **flags
        )


def test_rejects_authority_bearing_tournament_and_invalid_metrics():
    tournament, attestation, policy = make_inputs()
    unsafe = replace(tournament, model_activated=True)
    with pytest.raises(ExplorationPlanningError, match="authority"):
        FailureInformedExplorationPlanner().plan(
            unsafe, attestation, policy, verify_attestation=lambda report, envelope: True
        )
    bad_fitness = replace(tournament.scores[0].median_fitness)
    object.__setattr__(bad_fitness, "safety", float("nan"))
    bad_score = replace(tournament.scores[0], median_fitness=bad_fitness)
    bad_report = replace(tournament, scores=(bad_score,))
    bad_attestation = replace(attestation, report_digest=bad_report.digest)
    with pytest.raises(ExplorationPlanningError, match="metrics"):
        FailureInformedExplorationPlanner().plan(
            bad_report, bad_attestation, policy, verify_attestation=lambda report, envelope: True
        )


def test_exploration_allocation_is_deterministic_and_bounded():
    tournament, attestation, policy = make_inputs()
    planner = FailureInformedExplorationPlanner()
    first = planner.plan(tournament, attestation, policy, verify_attestation=lambda report, envelope: True)
    second = planner.plan(tournament, attestation, policy, verify_attestation=lambda report, envelope: True)
    assert first == second
    assert sum(x.exploration_share for x in first.profiles) <= 1.0
    assert all(2 <= x.recommended_repeats <= 4 for x in first.profiles)
