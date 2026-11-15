import hashlib

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeStrategyParameters,
)
from core.ai_factory_stage155_isolated_merge_experiments import (
    IndependentEvaluationEvidence, IsolatedMergeExperimentError,
    IsolatedMergeExperimentRunner, SandboxExecutionReceipt, SandboxPolicy,
)

SUITE = "a" * 64
DIGEST = "b" * 64
OUTPUT = "c" * 64
EVIDENCE = "d" * 64


def plan():
    return MergeEvaluationPlan(
        "plan-1", "candidate-1", 2, MergeAlgorithm.SLERP,
        MergeStrategyParameters(interpolation=.5), ("parent-a", "parent-b"),
        (DIGEST, "e" * 64), "f" * 64, SUITE, DIGEST, "parameter_merge",
    )


def fitness(*, accuracy=.91, instruction=.90, safety=.99, latency=90, memory=490, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


class Sandbox:
    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls = 0

    def execute(self, *, plan, policy):
        self.calls += 1
        values = dict(
            plan_id=plan.plan_id, recipe_digest=plan.recipe_digest,
            output_artifact_digest=OUTPUT, sandbox_id="sandbox-1",
            executor_id="executor-1", exit_code=0, network_was_disabled=True,
            parent_inputs_were_read_only=True, output_was_isolated=True,
            resource_limits_were_enforced=True, secrets_were_exposed=False,
        )
        values.update(self.overrides)
        return SandboxExecutionReceipt(**values)


class Evaluator:
    def __init__(self, evidence=None):
        self.evidence = evidence or IndependentEvaluationEvidence(
            "reviewer-1", OUTPUT, SUITE, fitness(accuracy=.92, latency=85),
            EVIDENCE, "signed",
        )
        self.calls = 0

    def evaluate(self, *, artifact_digest, evaluation_suite_digest):
        self.calls += 1
        assert artifact_digest == OUTPUT
        assert evaluation_suite_digest == SUITE
        return self.evidence


def execute(sandbox=None, evaluator=None, **kwargs):
    sandbox = sandbox or Sandbox()
    evaluator = evaluator or Evaluator()
    result = IsolatedMergeExperimentRunner().run(
        plan=plan(), approval_token="human-approval",
        verify_approval=lambda token, digest: token == "human-approval" and digest == DIGEST,
        sandbox=sandbox, evaluator=evaluator,
        verify_evaluation_evidence=lambda evidence: evidence.signature == "signed",
        baseline_fitness=fitness(), **kwargs,
    )
    return result, sandbox, evaluator


def test_approved_isolated_experiment_and_independent_improvement_proposal():
    result, sandbox, evaluator = execute()
    assert sandbox.calls == 1 and evaluator.calls == 1
    assert result.accepted_for_next_generation is True
    assert result.proposal_only is True
    assert result.generation_advanced is False
    assert result.model_activated is False
    assert result.production_switch_authorized is False


def test_rejects_missing_or_invalid_human_approval_before_sandbox():
    sandbox = Sandbox()
    with pytest.raises(IsolatedMergeExperimentError):
        IsolatedMergeExperimentRunner().run(
            plan=plan(), approval_token="bad",
            verify_approval=lambda token, digest: False,
            sandbox=sandbox, evaluator=Evaluator(),
            verify_evaluation_evidence=lambda evidence: True,
            baseline_fitness=fitness(),
        )
    assert sandbox.calls == 0


@pytest.mark.parametrize("override", [
    {"network_was_disabled": False},
    {"parent_inputs_were_read_only": False},
    {"output_was_isolated": False},
    {"resource_limits_were_enforced": False},
    {"secrets_were_exposed": True},
    {"exit_code": 1},
    {"recipe_digest": "0" * 64},
])
def test_rejects_failed_sandbox_guarantees(override):
    with pytest.raises(IsolatedMergeExperimentError):
        execute(sandbox=Sandbox(**override))


def test_rejects_same_executor_and_evaluator_identity():
    evaluator = Evaluator(IndependentEvaluationEvidence(
        "executor-1", OUTPUT, SUITE, fitness(accuracy=.92), EVIDENCE, "signed"))
    with pytest.raises(IsolatedMergeExperimentError):
        execute(evaluator=evaluator)


def test_rejects_tampered_or_unverified_evaluation_evidence():
    evaluator = Evaluator(IndependentEvaluationEvidence(
        "reviewer-1", "0" * 64, SUITE, fitness(accuracy=.92), EVIDENCE, "signed"))
    with pytest.raises(IsolatedMergeExperimentError):
        execute(evaluator=evaluator)
    with pytest.raises(IsolatedMergeExperimentError):
        IsolatedMergeExperimentRunner().run(
            plan=plan(), approval_token="human-approval",
            verify_approval=lambda token, digest: True,
            sandbox=Sandbox(), evaluator=Evaluator(),
            verify_evaluation_evidence=lambda evidence: False,
            baseline_fitness=fitness(),
        )


@pytest.mark.parametrize("metrics", [
    {"accuracy": .89},
    {"instruction": .89},
    {"safety": .90},
    {"latency": 120},
    {"memory": 600},
    {"regressions": 1},
])
def test_quality_or_safety_regression_is_not_admitted(metrics):
    result, _, _ = execute(evaluator=Evaluator(IndependentEvaluationEvidence(
        "reviewer-1", OUTPUT, SUITE, fitness(**metrics), EVIDENCE, "signed")))
    assert result.accepted_for_next_generation is False
    assert result.reasons


def test_no_improvement_is_not_admitted():
    result, _, _ = execute(evaluator=Evaluator(IndependentEvaluationEvidence(
        "reviewer-1", OUTPUT, SUITE, fitness(), EVIDENCE, "signed")))
    assert result.accepted_for_next_generation is False
    assert "no measurable Pareto improvement over baseline" in result.reasons


def test_policy_bounds_and_offline_defaults():
    policy = SandboxPolicy()
    assert policy.network_enabled is False
    assert policy.parent_artifacts_read_only is True
    with pytest.raises(ValueError):
        SandboxPolicy(network_enabled=True)
    with pytest.raises(ValueError):
        SandboxPolicy(max_runtime_seconds=99999)


def test_deterministic_outcome_digest():
    first, _, _ = execute()
    second, _, _ = execute()
    assert first.outcome_digest == second.outcome_digest


def test_rejects_plan_without_independent_evaluation_or_with_self_authority():
    from dataclasses import replace

    for bad_plan in (
        replace(plan(), independent_evaluation_required=False),
        replace(plan(), execution_authorized=True),
        replace(plan(), merge_authorized=True),
        replace(plan(), activation_authorized=True),
    ):
        with pytest.raises(IsolatedMergeExperimentError):
            IsolatedMergeExperimentRunner().run(
                plan=bad_plan, approval_token="human-approval",
                verify_approval=lambda token, digest: True,
                sandbox=Sandbox(), evaluator=Evaluator(),
                verify_evaluation_evidence=lambda evidence: True,
                baseline_fitness=fitness(),
            )
