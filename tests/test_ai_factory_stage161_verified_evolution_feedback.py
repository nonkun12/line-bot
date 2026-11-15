from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeStrategyParameters,
)
from core.ai_factory_stage155_isolated_merge_experiments import MergeExperimentOutcome
from core.ai_factory_stage156_authenticated_knowledge_transfer import Stage156SignedEvidence
from core.ai_factory_stage160_approved_experiment_gate import ApprovedExperimentExecution
from core.ai_factory_stage161_verified_evolution_feedback import (
    EvolutionFeedbackError, VerifiedEvolutionFeedbackLoop,
)

SUITE = "a" * 64
RECIPE = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64
CANDIDATE = "e" * 64
OUTPUT = "f" * 64
EVIDENCE = "1" * 64
OUTCOME_DIGEST = "2" * 64


def fitness(*, accuracy=.92, instruction=.91, safety=.99, latency=85, memory=480, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def fixtures():
    plan = MergeEvaluationPlan(
        "plan-161", "candidate-161", 7, MergeAlgorithm.SLERP,
        MergeStrategyParameters(interpolation=.5), ("parent-a", "parent-b"),
        (PARENT_A, PARENT_B), CANDIDATE, SUITE, RECIPE, "parameter_merge",
    )
    outcome = MergeExperimentOutcome(
        plan.plan_id, RECIPE, OUTPUT, EVIDENCE, "independent-reviewer",
        True, (), OUTCOME_DIGEST,
    )
    execution = ApprovedExperimentExecution(
        "proposal-161", "3" * 64, outcome, True, True,
    )
    evidence = Stage156SignedEvidence(
        OUTCOME_DIGEST, EVIDENCE, OUTPUT, SUITE, "independent-reviewer", 7,
        ("parent-a", "parent-b"), (PARENT_A, PARENT_B), fitness(),
        "signature-from-independent-verifier",
    )
    baseline = fitness(accuracy=.91, instruction=.90, safety=.98, latency=90, memory=500)
    return plan, outcome, execution, evidence, baseline


def ingest(loop=None, *, execution=None, plan=None, evidence=None, baseline=None, **kwargs):
    p, _, x, e, b = fixtures()
    return (loop or VerifiedEvolutionFeedbackLoop()).ingest(
        execution=execution or x, plan=plan or p, evidence=evidence or e,
        baseline_fitness=baseline or b,
        verify_stage155_evidence=lambda item: item.signature == "signature-from-independent-verifier",
        expected_suite_digest=SUITE, **kwargs,
    )


def test_verified_execution_returns_append_only_next_generation_feedback():
    loop = VerifiedEvolutionFeedbackLoop()
    receipt = ingest(loop)
    snapshot = loop.snapshot()
    assert receipt.proposal_id == "proposal-161"
    assert receipt.proposed_generation == 8
    assert receipt.pending_human_approval is True
    assert receipt.generation_advanced is False
    assert receipt.model_activated is False
    assert receipt.auto_adoption_authorized is False
    assert receipt.production_switch_authorized is False
    assert snapshot.proposal_only is True
    assert snapshot.knowledge.proposed_generations == (8,)
    assert snapshot.generation_advanced is False
    assert snapshot.digest == loop.snapshot().digest


@pytest.mark.parametrize("changes", [
    {"execution_requested_by_explicit_call": False},
    {"approval_verified_by_runner": False},
    {"proposal_only": False},
    {"generation_advanced": True},
    {"model_activated": True},
    {"production_switch_authorized": True},
])
def test_rejects_stage160_envelope_without_verified_approval_or_safe_flags(changes):
    plan, _, execution, evidence, baseline = fixtures()
    with pytest.raises(EvolutionFeedbackError, match="explicit approval|safe authority"):
        ingest(execution=replace(execution, **changes), plan=plan,
               evidence=evidence, baseline=baseline)


def test_rejects_outcome_plan_drift_and_bad_independent_evidence():
    plan, outcome, execution, evidence, baseline = fixtures()
    with pytest.raises(EvolutionFeedbackError, match="exact non-authoritative plan"):
        ingest(execution=replace(execution, outcome=replace(outcome, recipe_digest="9" * 64)),
               plan=plan, evidence=evidence, baseline=baseline)
    with pytest.raises(EvolutionFeedbackError, match="signature"):
        ingest(execution=execution, plan=plan,
               evidence=replace(evidence, signature="tampered"), baseline=baseline)


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_hold_kill_switch_and_budget_fail_closed(flags):
    with pytest.raises(EvolutionFeedbackError):
        ingest(**flags)


def test_rejects_replay_and_capacity_overflow():
    loop = VerifiedEvolutionFeedbackLoop(max_receipts=1)
    ingest(loop)
    with pytest.raises(EvolutionFeedbackError, match="duplicate or replayed"):
        ingest(loop)
    assert len(loop.snapshot().receipts) == 1


def test_rejects_unaccepted_experiment_outcome():
    plan, outcome, execution, evidence, baseline = fixtures()
    bad = replace(execution, outcome=replace(outcome, accepted_for_next_generation=False))
    with pytest.raises(EvolutionFeedbackError, match="Stage 155"):
        ingest(execution=bad, plan=plan, evidence=evidence, baseline=baseline)
