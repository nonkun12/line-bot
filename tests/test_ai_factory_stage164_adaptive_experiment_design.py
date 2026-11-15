from dataclasses import replace

import pytest

from core.ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionarySelectionPolicy, StrategyLearning,
)
from core.ai_factory_stage163_failure_informed_exploration import (
    AdaptiveExplorationPlan, StrategyFailureProfile,
)
from core.ai_factory_stage164_adaptive_experiment_design import (
    AdaptiveExperimentDesignError, AdaptiveExperimentDesigner, DesignAttestation,
)

SUITE = "a" * 64
SOURCE = "b" * 64


def make_inputs():
    profiles = (
        StrategyFailureProfile("slerp", 4, 0, 0, 0, 0, (), .30, 2, True),
        StrategyFailureProfile("ties", 4, 1, 0, 0, 0, ("variance",), .35, 3, True),
        StrategyFailureProfile("dare", 2, 0, 1, 0, 0, ("safety floor",), .35, 4, False),
    )
    exploration = AdaptiveExplorationPlan(
        "c" * 64, "d" * 64, SUITE, 7, profiles, 0, 1.0, SOURCE,
    )
    learning = StrategyLearning("slerp", 3, 2, .94, .99, 75, 400, .6, .08, ("e" * 64,))
    policy = EvolutionarySelectionPolicy("f" * 64, SUITE, (learning,), "1" * 64)
    attestation = DesignAttestation(SOURCE, SUITE, 7, "independent-evaluator", "signed-plan")
    return exploration, attestation, policy


def test_adapts_diagnostic_focus_and_search_space_without_authority():
    exploration, attestation, policy = make_inputs()
    report = AdaptiveExperimentDesigner().design(
        exploration, attestation, policy,
        verify_attestation=lambda plan, envelope: True,
    )
    recipes = {x.strategy: x for x in report.recipes}
    assert recipes["ties"].diagnostic_focus == ("repeatability_variance",)
    assert recipes["dare"].diagnostic_focus == ("safety",)
    assert recipes["slerp"].search_axes == (("interpolation_coefficient", .20, .80),)
    assert recipes["dare"].candidate_retention_eligible is False
    assert recipes["slerp"].historical_prior == .08
    assert all(x.evaluation_dimensions == ("accuracy", "instruction_following", "safety", "latency_ms", "memory_mb") for x in report.recipes)
    assert report.total_repeat_budget == 9
    assert report.proposal_only and not report.experiment_execution_authorized
    assert not report.model_mutation_authorized and not report.generation_advanced
    assert not report.model_activated and not report.production_switch_authorized


def test_design_is_deterministic_and_attestation_bound():
    exploration, attestation, policy = make_inputs()
    designer = AdaptiveExperimentDesigner()
    verify = lambda plan, envelope: True
    assert designer.design(exploration, attestation, policy, verify_attestation=verify) == designer.design(
        exploration, attestation, policy, verify_attestation=verify
    )
    with pytest.raises(AdaptiveExperimentDesignError, match="attestation"):
        designer.design(exploration, attestation, policy, verify_attestation=lambda plan, envelope: False)


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_fails_closed_on_global_gates(flags):
    exploration, attestation, policy = make_inputs()
    with pytest.raises(AdaptiveExperimentDesignError):
        AdaptiveExperimentDesigner().design(
            exploration, attestation, policy,
            verify_attestation=lambda plan, envelope: True, **flags
        )


def test_rejects_suite_drift_authority_and_repeat_budget_overflow():
    exploration, attestation, policy = make_inputs()
    with pytest.raises(AdaptiveExperimentDesignError, match="suite"):
        AdaptiveExperimentDesigner().design(
            exploration, attestation, replace(policy, evaluation_suite_digest="2" * 64),
            verify_attestation=lambda plan, envelope: True,
        )
    unsafe = replace(exploration, model_activated=True)
    with pytest.raises(AdaptiveExperimentDesignError, match="authority"):
        AdaptiveExperimentDesigner().design(
            unsafe, attestation, policy, verify_attestation=lambda plan, envelope: True,
        )
    with pytest.raises(AdaptiveExperimentDesignError, match="repeat budget"):
        AdaptiveExperimentDesigner().design(
            exploration, attestation, policy,
            verify_attestation=lambda plan, envelope: True, max_total_repeats=8,
        )


def test_orchestration_route_has_no_weight_search_axes():
    exploration, attestation, policy = make_inputs()
    profile = StrategyFailureProfile("multi_model_orchestration", 2, 0, 0, 0, 0, (), 1.0, 2, True)
    report = replace(exploration, profiles=(profile,), total_exploration_share=1.0)
    result = AdaptiveExperimentDesigner().design(
        report, attestation, policy, verify_attestation=lambda plan, envelope: True,
    )
    assert result.recipes[0].search_axes == ()
