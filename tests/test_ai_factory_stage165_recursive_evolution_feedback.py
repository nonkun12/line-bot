from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeStrategyParameters,
)
from core.ai_factory_stage156_authenticated_knowledge_transfer import Stage156SignedEvidence
from core.ai_factory_stage160_approved_experiment_gate import ApprovedExperimentExecution
from core.ai_factory_stage164_adaptive_experiment_design import (
    AdaptiveExperimentDesignReport, AdaptiveExperimentRecipe, DesignAttestation,
)
from core.ai_factory_stage155_isolated_merge_experiments import MergeExperimentOutcome
from core.ai_factory_stage165_recursive_evolution_feedback import (
    RecursiveEvolutionFeedbackError, RecursiveEvolutionFeedbackIntegrator,
)

SUITE = "a" * 64
DESIGN = "b" * 64
RECIPE = "c" * 64
PARENT_A = "d" * 64
PARENT_B = "e" * 64
CANDIDATE = "f" * 64
OUTPUT = "1" * 64
EVIDENCE = "2" * 64
OUTCOME = "3" * 64


def fitness(accuracy=.92, instruction=.91, safety=.99, latency=85, memory=480, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def fixtures(measured=None, accepted=True):
    recipe = AdaptiveExperimentRecipe(
        "slerp", ("balanced_quality_and_resource_validation",),
        ("accuracy", "instruction_following", "safety", "latency_ms", "memory_mb"),
        (("interpolation_coefficient", .20, .80),), 2, .5, .04, True,
    )
    design = AdaptiveExperimentDesignReport(
        "4" * 64, "5" * 64, SUITE, 7, (recipe,), 2, DESIGN,
    )
    attestation = DesignAttestation(DESIGN, SUITE, 7, "independent-designer", "signature")
    plan = MergeEvaluationPlan(
        "plan-165", "candidate-165", 7, MergeAlgorithm.SLERP,
        MergeStrategyParameters(interpolation=.5), ("parent-a", "parent-b"),
        (PARENT_A, PARENT_B), CANDIDATE, SUITE, RECIPE, "parameter_merge",
    )
    measured = measured or fitness()
    outcome = MergeExperimentOutcome(
        plan.plan_id, RECIPE, OUTPUT, EVIDENCE, "independent-evaluator",
        accepted, (), OUTCOME,
    )
    execution = ApprovedExperimentExecution("4" * 64, "5" * 64, outcome, True, True)
    evidence = Stage156SignedEvidence(
        OUTCOME, EVIDENCE, OUTPUT, SUITE, "independent-evaluator", 7,
        ("parent-a", "parent-b"), (PARENT_A, PARENT_B), measured, "signed-evidence",
    )
    baseline = fitness(.91, .90, .98, 90, 500)
    return design, attestation, execution, plan, evidence, baseline


def ingest(loop=None, **changes):
    d, a, x, p, e, b = fixtures()
    args = dict(
        design=d, design_attestation=a, execution=x, plan=p, evidence=e,
        baseline_fitness=b,
        verify_design_attestation=lambda report, envelope: True,
        verify_trial_evidence=lambda signed: signed.signature == "signed-evidence",
    )
    args.update(changes)
    return (loop or RecursiveEvolutionFeedbackIntegrator()).ingest(**args)


def test_records_verified_improvement_and_next_generation_guidance():
    loop = RecursiveEvolutionFeedbackIntegrator()
    record = ingest(loop)
    snapshot = loop.snapshot()
    assert record.classification == "IMPROVED"
    assert record.proposed_generation == 8
    assert record.pending_human_approval is True
    assert record.generation_advanced is False and record.model_activated is False
    assert snapshot.summaries[0].improved == 1
    assert "repeatability evidence" in snapshot.summaries[0].next_generation_guidance[0]
    assert snapshot.digest == loop.snapshot().digest


def test_records_safety_failure_and_regression_without_transferring_candidate():
    measured = fitness(accuracy=.90, instruction=.88, safety=.80, latency=110, memory=600, regressions=1)
    d, a, x, p, e, b = fixtures(measured=measured, accepted=False)
    loop = RecursiveEvolutionFeedbackIntegrator()
    record = ingest(loop, design=d, design_attestation=a, execution=x, plan=p, evidence=e, baseline_fitness=b)
    assert record.classification == "SAFETY_FAILURE"
    summary = loop.snapshot().summaries[0]
    assert summary.safety_failures == 1 and summary.regressed == 0
    assert "candidate retention disabled" in summary.next_generation_guidance[0]


def test_records_stagnation_and_does_not_claim_improvement():
    measured = fitness(.91, .90, .98, 90, 500)
    d, a, x, p, e, b = fixtures(measured=measured, accepted=False)
    record = ingest(design=d, design_attestation=a, execution=x, plan=p, evidence=e, baseline_fitness=b)
    assert record.classification == "STAGNANT"


def test_rejects_bad_attestation_suite_drift_and_parameter_outside_design():
    d, a, x, p, e, b = fixtures()
    with pytest.raises(RecursiveEvolutionFeedbackError, match="attestation"):
        ingest(design=d, design_attestation=a, execution=x, plan=p, evidence=e, baseline_fitness=b,
               verify_design_attestation=lambda report, envelope: False)
    with pytest.raises(RecursiveEvolutionFeedbackError, match="suite"):
        ingest(design=d, design_attestation=replace(a, evaluation_suite_digest="9" * 64),
               execution=x, plan=p, evidence=e, baseline_fitness=b)
    with pytest.raises(RecursiveEvolutionFeedbackError, match="search envelope"):
        ingest(design=d, design_attestation=a, execution=x,
               plan=replace(p, parameters=MergeStrategyParameters(interpolation=.95)),
               evidence=e, baseline_fitness=b)


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_gates_fail_closed(flags):
    with pytest.raises(RecursiveEvolutionFeedbackError):
        ingest(**flags)


def test_rejects_replay_and_execution_without_explicit_approval():
    loop = RecursiveEvolutionFeedbackIntegrator()
    ingest(loop)
    with pytest.raises(RecursiveEvolutionFeedbackError, match="replay"):
        ingest(loop)
    d, a, x, p, e, b = fixtures()
    with pytest.raises(RecursiveEvolutionFeedbackError, match="explicit one-time"):
        ingest(design=d, design_attestation=a,
               execution=replace(x, approval_verified_by_runner=False),
               plan=p, evidence=e, baseline_fitness=b)


def test_rejects_acceptance_flag_that_disagrees_with_signed_metrics():
    d, a, x, p, e, b = fixtures(measured=fitness(.90, .89, .97, 95, 520), accepted=True)
    with pytest.raises(RecursiveEvolutionFeedbackError, match="acceptance flag"):
        ingest(design=d, design_attestation=a, execution=x, plan=p, evidence=e, baseline_fitness=b)
