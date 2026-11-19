from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeEvaluationPlanReport, MergeStrategyParameters,
)
from core.ai_factory_stage155_isolated_merge_experiments import (
    IndependentEvaluationEvidence, SandboxExecutionReceipt,
)
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage159_evolutionary_experiment_handoff import EvolutionaryExperimentHandoff
from core.ai_factory_stage160_approved_experiment_gate import (
    ApprovedEvolutionaryExperimentGate, ApprovedExperimentGateError,
)

SUITE = "a" * 64
ARTIFACT = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64


def setup_case():
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
    score = StrategyScore("candidate-1", "slerp", 2, ("eval-a", "eval-b"),
                          fitness, True, (), True, "f" * 64)
    tournament = MergeTournamentReport(
        plans.digest, SUITE, (score,), (("candidate-1", "slerp"),), (), "7" * 64,
    )
    proposal = EvolutionaryExperimentHandoff().prepare(
        plans=plans, tournament=tournament
    ).proposals[0]
    return plan, proposal


class Sandbox:
    def execute(self, *, plan, policy):
        return SandboxExecutionReceipt(
            plan.plan_id, plan.recipe_digest, "1" * 64, "sandbox-1", "executor-1",
            0, True, True, True, True, False,
        )


class Evaluator:
    def evaluate(self, *, artifact_digest, evaluation_suite_digest):
        measured = Fitness(.94, .93, .99, 90, 470, 0, SUITE)
        return IndependentEvaluationEvidence(
            "independent-evaluator", artifact_digest, evaluation_suite_digest,
            measured, "2" * 64, "signed-evidence",
        )


def test_explicit_one_time_approval_runs_only_isolated_experiment_and_returns_proposal():
    plan, proposal = setup_case()
    approval_calls = []
    result = ApprovedEvolutionaryExperimentGate().execute(
        proposal=proposal, plan=plan, approval_token="human-one-time-token",
        verify_approval=lambda token, digest: approval_calls.append((token, digest)) or True,
        sandbox=Sandbox(), evaluator=Evaluator(),
        verify_evaluation_evidence=lambda evidence: True,
        baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE),
    )
    assert len(approval_calls) == 1
    assert approval_calls[0] == ("human-one-time-token", plan.recipe_digest)
    assert result.execution_requested_by_explicit_call is True
    assert result.approval_verified_by_runner is True
    assert result.outcome.accepted_for_next_generation is True
    assert result.proposal_only is True
    assert result.generation_advanced is False
    assert result.model_activated is False
    assert result.production_switch_authorized is False


def test_rejects_tampered_proposal_and_plan_lineage_before_execution():
    plan, proposal = setup_case()
    with pytest.raises(ApprovedExperimentGateError, match="digest or identity"):
        ApprovedEvolutionaryExperimentGate().execute(
            proposal=replace(proposal, recipe_digest="f" * 64), plan=plan,
            approval_token="token", verify_approval=lambda *_: True,
            sandbox=Sandbox(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda _: True,
            baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE),
        )
    with pytest.raises(ApprovedExperimentGateError, match="exact Stage 159"):
        ApprovedEvolutionaryExperimentGate().execute(
            proposal=proposal, plan=replace(plan, recipe_digest="f" * 64),
            approval_token="token", verify_approval=lambda *_: True,
            sandbox=Sandbox(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda _: True,
            baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE),
        )


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_hold_kill_switch_and_budget_fail_closed(flags):
    plan, proposal = setup_case()
    with pytest.raises(ApprovedExperimentGateError):
        ApprovedEvolutionaryExperimentGate().execute(
            proposal=proposal, plan=plan, approval_token="token",
            verify_approval=lambda *_: True, sandbox=Sandbox(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda _: True,
            baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE), **flags,
        )


def test_missing_or_rejected_human_approval_never_invokes_sandbox():
    plan, proposal = setup_case()

    class NeverRun:
        def execute(self, **_):
            pytest.fail("sandbox must not run without verified human approval")

    with pytest.raises(ApprovedExperimentGateError, match="token"):
        ApprovedEvolutionaryExperimentGate().execute(
            proposal=proposal, plan=plan, approval_token="",
            verify_approval=lambda *_: True, sandbox=NeverRun(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda _: True,
            baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE),
        )
    with pytest.raises(Exception, match="approval"):
        ApprovedEvolutionaryExperimentGate().execute(
            proposal=proposal, plan=plan, approval_token="bad-token",
            verify_approval=lambda *_: False, sandbox=NeverRun(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda _: True,
            baseline_fitness=Fitness(.93, .92, .99, 100, 500, 0, SUITE),
        )
