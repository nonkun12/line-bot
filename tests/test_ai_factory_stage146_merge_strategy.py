import hashlib

import pytest

from core.ai_factory_stage141_evolution import ModelDescriptor
from core.ai_factory_stage145_improvement_gate import (
    EvolutionDecision, GenerationImprovementReport,
)
from core.ai_factory_stage142_lineage import ModelLineageRecord
from core.ai_factory_stage141_evolution import CandidateStatus
from core.ai_factory_stage146_merge_strategy import (
    EvolutionaryMergeStrategyPlanner, MergeMethod, MergeReadiness, MergeRecipeError,
)


def parent(name, *, architecture="transformer-x", tokenizer="tok-v1",
           schema="schema-v1", fmt="safetensors", quant="fp16", adapter=""):
    return ModelDescriptor(
        model_id=name, architecture=architecture, tokenizer_fingerprint=tokenizer,
        tensor_schema_fingerprint=schema, artifact_format=fmt,
        artifact_digest=hashlib.sha256(name.encode()).hexdigest(),
        license_id="license-reviewed", provenance="signed-local-manifest",
        quantization=quant, local_artifact_available=True,
        adapter_base_fingerprint=adapter,
    )


def improved_report(parents):
    record = ModelLineageRecord(
        candidate_id="child-146",
        parent_ids=tuple(p.model_id for p in parents),
        parent_artifact_digests=tuple(p.artifact_digest for p in parents),
        strategy="parameter_merge", generation=2,
        evaluated_artifact_digest="c" * 64,
        evaluation_suite_digest="e" * 64,
        evaluator_id="independent-lab", evidence_digest="d" * 64,
        status=CandidateStatus.PENDING_HUMAN_APPROVAL, enabled=False,
    )
    return GenerationImprovementReport(
        "child-146", 2, EvolutionDecision.IMPROVED, (), record, "improved",
    )


def test_compatible_dense_models_get_slerp_proposal_only():
    parents = (parent("a"), parent("b"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(improved_report(parents), parents)
    assert recipe.method is MergeMethod.SLERP
    assert recipe.readiness is MergeReadiness.PROPOSAL_ONLY
    assert recipe.coefficients == (.5, .5)
    assert recipe.output_artifact_digest == "c" * 64


def test_ties_and_dare_require_bounded_density():
    parents = (parent("a"), parent("b"))
    planner = EvolutionaryMergeStrategyPlanner()
    with pytest.raises(MergeRecipeError, match="density"):
        planner.plan(improved_report(parents), parents, requested_method=MergeMethod.TIES)
    recipe = planner.plan(improved_report(parents), parents,
                          requested_method=MergeMethod.DARE, density=.65, seed=42)
    assert recipe.method is MergeMethod.DARE
    assert recipe.density == .65
    assert recipe.seed == 42


def test_quantization_or_tokenizer_mismatch_falls_back_to_orchestration():
    parents = (parent("a"), parent("b", quant="q4_k_m"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(improved_report(parents), parents)
    assert recipe.method is MergeMethod.ORCHESTRATION
    assert recipe.readiness is MergeReadiness.ORCHESTRATION_ONLY
    assert any("quantization" in reason for reason in recipe.reasons)


def test_gguf_is_not_treated_as_dense_tensor_merge_input():
    parents = (parent("a", fmt="gguf"), parent("b", fmt="gguf"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(improved_report(parents), parents)
    assert recipe.method is MergeMethod.ORCHESTRATION
    assert any("dense" in reason for reason in recipe.reasons)


def test_lora_requires_shared_adapter_base():
    parents = (parent("a", adapter="base-x"), parent("b", adapter="base-x"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(
        improved_report(parents), parents, requested_method=MergeMethod.LORA,
    )
    assert recipe.method is MergeMethod.LORA
    assert recipe.readiness is MergeReadiness.PROPOSAL_ONLY
    mismatch = (parents[0], parent("c", adapter="base-y"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(
        improved_report(mismatch), mismatch, requested_method=MergeMethod.LORA,
    )
    assert recipe.method is MergeMethod.ORCHESTRATION


def test_lineage_digest_mismatch_is_rejected():
    parents = (parent("a"), parent("b"))
    report = improved_report(parents)
    altered = (parent("a"), parent("different"))
    with pytest.raises(MergeRecipeError, match="lineage"):
        EvolutionaryMergeStrategyPlanner().plan(report, altered)


def test_non_improved_report_cannot_create_merge_recipe():
    parents = (parent("a"), parent("b"))
    report = improved_report(parents)
    blocked = GenerationImprovementReport(
        report.candidate_id, report.generation, EvolutionDecision.NO_IMPROVEMENT,
        (), None, "no improvement",
    )
    with pytest.raises(MergeRecipeError, match="IMPROVED"):
        EvolutionaryMergeStrategyPlanner().plan(blocked, parents)


def test_coefficients_must_be_finite_nonnegative_and_normalized():
    parents = (parent("a"), parent("b"))
    planner = EvolutionaryMergeStrategyPlanner()
    with pytest.raises(MergeRecipeError, match="sum to 1"):
        planner.plan(improved_report(parents), parents, coefficients=(.8, .3))
    with pytest.raises(MergeRecipeError, match="non-negative"):
        planner.plan(improved_report(parents), parents, coefficients=(1.2, -.2))


def test_slerp_requires_exactly_two_parents():
    parents = (parent("a"), parent("b"), parent("c"))
    with pytest.raises(MergeRecipeError, match="exactly two"):
        EvolutionaryMergeStrategyPlanner().plan(improved_report(parents), parents)


def test_orchestration_can_be_requested_explicitly():
    parents = (parent("a"), parent("b"))
    recipe = EvolutionaryMergeStrategyPlanner().plan(
        improved_report(parents), parents, requested_method=MergeMethod.ORCHESTRATION,
    )
    assert recipe.readiness is MergeReadiness.ORCHESTRATION_ONLY
    assert recipe.coefficients == ()
