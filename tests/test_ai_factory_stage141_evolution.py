import pytest

from core.ai_factory_stage141_evolution import (
    CandidateStatus, EvolutionaryModelMergePlanner, EvolutionarySafety, Fitness,
    MergeStrategy, ModelDescriptor, assess_compatibility, dominates, pareto_frontier,
)


def model(name, **overrides):
    values = dict(
        model_id=name, architecture="transformer-x", tokenizer_fingerprint="tok-a",
        tensor_schema_fingerprint="tensor-a", artifact_format="safetensors",
        artifact_digest=f"digest-{name}", license_id="license-a",
        provenance="local-manifest", local_artifact_available=True,
    )
    values.update(overrides)
    return ModelDescriptor(**values)


def fitness(**overrides):
    values = dict(accuracy=.9, instruction_following=.9, safety=.99,
                  latency_ms=100, memory_mb=1024, regression_count=0,
                  evaluation_suite_digest="eval-v1-sha256")
    values.update(overrides)
    return Fitness(**values)


def test_identical_local_metadata_allows_parameter_merge_proposal():
    report = assess_compatibility((model("a"), model("b")))
    assert report.compatible
    assert report.strategy is MergeStrategy.PARAMETER


def test_incompatible_architectures_fall_back_to_orchestration_not_weight_merge():
    report = assess_compatibility((
        model("bonsai", architecture="architecture-bonsai"),
        model("lfm3", architecture="architecture-lfm3"),
    ))
    assert report.compatible
    assert report.strategy is MergeStrategy.ORCHESTRATION
    assert any("no tensors combined" in reason for reason in report.reasons)


def test_explicit_parameter_merge_rejects_incompatible_tokenizers():
    report = assess_compatibility((
        model("a"), model("b", tokenizer_fingerprint="different-tokenizer")
    ), requested_strategy=MergeStrategy.PARAMETER)
    assert not report.compatible


def test_missing_local_artifacts_never_claim_parameter_merge():
    report = assess_compatibility((
        model("a"), model("b", local_artifact_available=False)
    ))
    assert report.strategy is MergeStrategy.ORCHESTRATION


def test_adapter_merge_requires_same_explicit_base():
    report = assess_compatibility((
        model("a", adapter_base_fingerprint="base-1"),
        model("b", adapter_base_fingerprint="base-2"),
    ), requested_strategy=MergeStrategy.ADAPTER)
    assert not report.compatible


def test_safety_gate_stops_before_candidate_creation():
    report = EvolutionaryModelMergePlanner().plan(
        "tick-1", ((model("a"), model("b")),), (fitness(),),
        safety=EvolutionarySafety(hold_active=True),
    )
    assert report.candidates == ()
    assert report.stopped_reason == "HOLD is active"


def test_candidate_count_is_bounded_to_four_and_configured_limit():
    groups = tuple((model(f"a{i}"), model(f"b{i}")) for i in range(3))
    report = EvolutionaryModelMergePlanner().plan(
        "tick-2", groups, (fitness(), fitness(), fitness()),
        safety=EvolutionarySafety(max_candidates_per_tick=2),
    )
    assert report.candidates == ()
    assert report.stopped_reason == "candidate limit exceeded"


def test_safety_regression_and_missing_eval_evidence_reject_candidate():
    planner = EvolutionaryModelMergePlanner()
    low_safety = planner.plan("tick-3", ((model("a"), model("b")),),
                              (fitness(safety=.8),))
    regression = planner.plan("tick-4", ((model("a"), model("b")),),
                              (fitness(regression_count=1),))
    assert low_safety.candidates == ()
    assert regression.candidates == ()
    with pytest.raises(ValueError, match="evaluation_suite_digest is required"):
        fitness(evaluation_suite_digest="")


def test_pareto_frontier_keeps_tradeoffs_and_rejects_dominated_candidate():
    planner = EvolutionaryModelMergePlanner()
    groups = (
        (model("a1"), model("b1")),
        (model("a2"), model("b2")),
        (model("a3"), model("b3")),
    )
    scores = (
        fitness(accuracy=.95, latency_ms=180),
        fitness(accuracy=.91, latency_ms=80),
        fitness(accuracy=.89, latency_ms=200),
    )
    report = planner.plan(
        "tick-6", groups, scores,
        safety=EvolutionarySafety(max_candidates_per_tick=4),
    )
    assert len(report.candidates) == 3
    assert report.candidates[2].candidate_id not in report.pareto_frontier
    assert len(report.pareto_frontier) == 2


def test_candidates_are_pending_only_and_never_enabled():
    report = EvolutionaryModelMergePlanner().plan(
        "tick-7", ((model("a"), model("b")),), (fitness(),)
    )
    candidate = report.candidates[0]
    assert candidate.status is CandidateStatus.PENDING_HUMAN_APPROVAL
    assert candidate.enabled is False


def test_dominance_requires_no_worse_metrics_and_one_strict_improvement():
    assert dominates(fitness(accuracy=.95), fitness(accuracy=.9))
    assert not dominates(fitness(), fitness())
