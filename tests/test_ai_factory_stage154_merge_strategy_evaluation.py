import hashlib

import pytest

from core.ai_factory_stage141_evolution import Fitness, ModelDescriptor, MergeStrategy
from core.ai_factory_stage149_evolutionary_selection import EvolutionPopulationEntry, EvolutionPopulationSnapshot
from core.ai_factory_stage153_generation_model_selection import (
    CandidateModelEvidence, EvolutionaryGenerationSelector,
)
from core.ai_factory_stage154_merge_strategy_evaluation import (
    EvolutionaryMergeEvaluationPlanner, MergeAlgorithm, MergeEvaluationPlanError,
    MergeStrategyParameters,
)

SUITE = "a" * 64


def descriptor(name, *, digest=None, arch="llama", quant="bf16", provenance="local-verified", local=True):
    return ModelDescriptor(name, arch, "tok", "tensor-schema", "safetensors",
                           digest or hashlib.sha256(name.encode()).hexdigest(),
                           "license-v1", provenance, quant, local)


def item(cid="cand-1", *, parents=None, local=True, quant="bf16", provenance="local-verified"):
    parents = parents or (descriptor("parent-a", local=local, quant=quant, provenance=provenance),
                          descriptor("parent-b", local=local, quant=quant, provenance=provenance))
    artifact = hashlib.sha256((cid + "-artifact").encode()).hexdigest()
    evidence = hashlib.sha256((cid + "-evidence").encode()).hexdigest()
    fitness = Fitness(.99, .98, .99, 100, 512, 0, SUITE)
    entry = EvolutionPopulationEntry(cid, 1, tuple(p.model_id for p in parents),
                                     artifact, evidence, SUITE, fitness)
    return CandidateModelEvidence(entry, tuple(parents))


def selected(items):
    entries = tuple(x.entry for x in items)
    snap = EvolutionPopulationSnapshot(entries, tuple(x.entry.candidate_id for x in items),
                                       (1,), 64)
    return EvolutionaryGenerationSelector().select(snap, items, expected_suite_digest=SUITE)


def test_plans_all_supported_algorithms_proposal_only():
    items = [item()]
    selection = selected(items)
    report = EvolutionaryMergeEvaluationPlanner().plan(
        selection, items, expected_suite_digest=SUITE)
    assert {x.algorithm for x in report.plans} == {
        MergeAlgorithm.SLERP, MergeAlgorithm.TIES, MergeAlgorithm.DARE,
        MergeAlgorithm.TASK_ARITHMETIC,
    }
    assert all(x.execution_authorized is False and x.merge_authorized is False
               and x.activation_authorized is False for x in report.plans)
    assert report.proposal_only and not report.tensors_read and not report.weights_modified
    assert report.inference_executed is False and report.generation_advanced is False


def test_deterministic_recipe_digest_and_parent_artifact_binding():
    items = [item()]
    selection = selected(items)
    planner = EvolutionaryMergeEvaluationPlanner()
    first = planner.plan(selection, items, expected_suite_digest=SUITE)
    second = planner.plan(selection, items, expected_suite_digest=SUITE)
    assert first.digest == second.digest
    assert [x.recipe_digest for x in first.plans] == [x.recipe_digest for x in second.plans]
    assert all(x.parent_artifact_digests == tuple(p.artifact_digest for p in items[0].parent_descriptors)
               for x in first.plans)


def test_incompatible_architecture_quantization_provenance_and_nonlocal_route_to_orchestration():
    cases = [
        item(parents=(descriptor("a"), descriptor("b", arch="other"))),
        item(parents=(descriptor("a"), descriptor("b", quant="int8"))),
        item(parents=(descriptor("a"), descriptor("b", provenance="unverified"))),
        item(local=False),
    ]
    for candidate in cases:
        report = EvolutionaryMergeEvaluationPlanner().plan(
            selected([candidate]), [candidate], expected_suite_digest=SUITE)
        assert report.plans == ()
        assert report.orchestration_routes
        assert report.orchestration_routes[0].weight_merge_proposed is False


def test_rejects_suite_drift_and_tampered_parent_digest():
    candidate = item()
    selection = selected([candidate])
    with pytest.raises(MergeEvaluationPlanError):
        EvolutionaryMergeEvaluationPlanner().plan(selection, [candidate], expected_suite_digest="b" * 64)
    broken_parent = ModelDescriptor("parent-a", "llama", "tok", "tensor-schema",
                                    "safetensors", "not-a-digest", "license-v1",
                                    "local-verified", "bf16", True)
    broken = item(parents=(broken_parent, candidate.parent_descriptors[1]))
    with pytest.raises(MergeEvaluationPlanError):
        EvolutionaryMergeEvaluationPlanner().plan(selection, [broken], expected_suite_digest=SUITE)


def test_strategy_parameter_bounds_and_type_checks():
    planner = EvolutionaryMergeEvaluationPlanner()
    candidate = item()
    selection = selected([candidate])
    bad_grids = [
        ((MergeAlgorithm.SLERP, MergeStrategyParameters(interpolation=1.5)),),
        ((MergeAlgorithm.TIES, MergeStrategyParameters(density=0, merge_coefficient=1)),),
        ((MergeAlgorithm.DARE, MergeStrategyParameters(density=.5, merge_coefficient=3)),),
        ((MergeAlgorithm.TASK_ARITHMETIC, MergeStrategyParameters(merge_coefficient=float("nan"))),),
        ((MergeAlgorithm.LORA, MergeStrategyParameters(lora_rank=0, lora_alpha=8)),),
        ((MergeAlgorithm.LORA, MergeStrategyParameters(lora_rank=8, lora_alpha=0)),),
    ]
    for grid in bad_grids:
        with pytest.raises(MergeEvaluationPlanError):
            planner.plan(selection, [candidate], expected_suite_digest=SUITE, parameter_grid=grid)


def test_candidate_cap_and_fail_closed_controls():
    candidate = item()
    selection = selected([candidate])
    with pytest.raises(MergeEvaluationPlanError):
        EvolutionaryMergeEvaluationPlanner(max_plans=2).plan(
            selection, [candidate], expected_suite_digest=SUITE)
    for kwargs in ({"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False}):
        with pytest.raises(MergeEvaluationPlanError):
            EvolutionaryMergeEvaluationPlanner().plan(
                selection, [candidate], expected_suite_digest=SUITE, **kwargs)


def test_requires_exact_stage153_candidate_set_and_survivors():
    candidate = item()
    selection = selected([candidate])
    with pytest.raises(MergeEvaluationPlanError):
        EvolutionaryMergeEvaluationPlanner().plan(
            selection, [], expected_suite_digest=SUITE)
    with pytest.raises(MergeEvaluationPlanError):
        EvolutionaryMergeEvaluationPlanner().plan(
            selection, [candidate, item("extra")], expected_suite_digest=SUITE)


def test_lora_parameter_contract_is_bounded():
    candidate = item()
    selection = selected([candidate])
    report = EvolutionaryMergeEvaluationPlanner().plan(
        selection, [candidate], expected_suite_digest=SUITE,
        parameter_grid=((MergeAlgorithm.LORA, MergeStrategyParameters(lora_rank=16, lora_alpha=32)),))
    assert len(report.plans) == 1
    assert report.plans[0].algorithm is MergeAlgorithm.LORA
