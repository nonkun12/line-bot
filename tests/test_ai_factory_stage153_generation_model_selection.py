import hashlib

import pytest

from core.ai_factory_stage141_evolution import Fitness, ModelDescriptor, MergeStrategy
from core.ai_factory_stage149_evolutionary_selection import (
    EvolutionPopulationEntry, EvolutionPopulationSnapshot,
)
from core.ai_factory_stage153_generation_model_selection import (
    CandidateModelEvidence, EvolutionaryGenerationSelector, GenerationSelectionError,
    SelectionDecision,
)

SUITE = "a" * 64


def parent(name, digest, *, arch="llama", tokenizer="tok", schema="schema", fmt="safetensors", local=True):
    return ModelDescriptor(name, arch, tokenizer, schema, fmt, digest, "license-v1",
                           "local-verified", "bf16", local)


def candidate(cid, generation, accuracy, parents=("p1", "p2"), *, safety=.99, regression=0):
    artifact = hashlib.sha256(cid.encode()).hexdigest()
    evidence = hashlib.sha256((cid + "-evidence").encode()).hexdigest()
    fit = Fitness(accuracy, accuracy, safety, 100 + (1-accuracy)*100,
                  512, regression, SUITE)
    entry = EvolutionPopulationEntry(cid, generation, tuple(parents), artifact,
                                     evidence, SUITE, fit)
    descriptors = tuple(parent(pid, hashlib.sha256(pid.encode()).hexdigest()) for pid in parents)
    return CandidateModelEvidence(entry, descriptors)


def snapshot(items):
    entries = tuple(sorted((x.entry for x in items), key=lambda x: (x.generation, x.candidate_id)))
    frontier = tuple(sorted(
        x.candidate_id for x in entries
        if not any(y.candidate_id != x.candidate_id and
                   (y.fitness.accuracy >= x.fitness.accuracy and
                    y.fitness.instruction_following >= x.fitness.instruction_following and
                    y.fitness.safety >= x.fitness.safety and
                    y.fitness.latency_ms <= x.fitness.latency_ms and
                    y.fitness.memory_mb <= x.fitness.memory_mb and
                    y.fitness.regression_count <= x.fitness.regression_count and
                    (y.fitness.accuracy > x.fitness.accuracy or
                     y.fitness.instruction_following > x.fitness.instruction_following or
                     y.fitness.safety > x.fitness.safety or
                     y.fitness.latency_ms < x.fitness.latency_ms or
                     y.fitness.memory_mb < x.fitness.memory_mb or
                     y.fitness.regression_count < x.fitness.regression_count))
                   for y in entries)
    ))
    return EvolutionPopulationSnapshot(entries, frontier, tuple(sorted({x.generation for x in entries})), 64)


def test_selects_pareto_survivors_and_emits_proposal_only_report():
    items = [candidate("c1", 1, .80), candidate("c2", 2, .90, ("p3", "p4")),
             candidate("c3", 2, .85, ("p5", "p6"))]
    report = EvolutionaryGenerationSelector(max_survivors=2).select(
        snapshot(items), items, expected_suite_digest=SUITE)
    assert report.next_generation == 3
    assert len(report.survivor_candidate_ids) == 2
    assert all(x.execution_authorized is False and x.merge_authorized is False
               and x.activation_authorized is False for x in report.selections)
    assert report.auto_advance is False and report.proposal_only is True


def test_routes_incompatible_parent_metadata_to_orchestration_only():
    item = candidate("c1", 1, .9)
    bad = parent("p2", hashlib.sha256(b"p2").hexdigest(), arch="different")
    item = CandidateModelEvidence(item.entry, (item.parent_descriptors[0], bad))
    report = EvolutionaryGenerationSelector().select(
        snapshot([item]), [item], expected_suite_digest=SUITE)
    assert report.selections[0].merge_strategy is MergeStrategy.ORCHESTRATION


def test_rejects_suite_drift_and_missing_population_entries():
    items = [candidate("c1", 1, .9), candidate("c2", 2, .91, ("p3", "p4"))]
    with pytest.raises(GenerationSelectionError):
        EvolutionaryGenerationSelector().select(snapshot(items), items, expected_suite_digest="b"*64)
    with pytest.raises(GenerationSelectionError):
        EvolutionaryGenerationSelector().select(snapshot(items), items[:1], expected_suite_digest=SUITE)


def test_rejects_enabled_candidate_or_safety_regression():
    item = candidate("c1", 1, .9)
    enabled = EvolutionPopulationEntry(**{**item.entry.__dict__, "enabled": True})
    with pytest.raises(GenerationSelectionError):
        EvolutionaryGenerationSelector().select(snapshot([item]), [CandidateModelEvidence(enabled, item.parent_descriptors)],
                                                 expected_suite_digest=SUITE)
    unsafe = candidate("unsafe", 1, .9, safety=.90)
    with pytest.raises(GenerationSelectionError):
        EvolutionaryGenerationSelector().select(snapshot([unsafe]), [unsafe], expected_suite_digest=SUITE)


def test_recomputes_frontier_and_rejects_forged_cached_frontier():
    items = [candidate("c1", 1, .8), candidate("c2", 1, .9)]
    forged = EvolutionPopulationSnapshot(snapshot(items).entries, ("c1",), (1,), 64)
    with pytest.raises(GenerationSelectionError):
        EvolutionaryGenerationSelector().select(forged, items, expected_suite_digest=SUITE)


def test_deterministic_digest_and_fail_closed_controls():
    items = [candidate("c1", 1, .8), candidate("c2", 2, .9, ("p3", "p4"))]
    selector = EvolutionaryGenerationSelector()
    a = selector.select(snapshot(items), items, expected_suite_digest=SUITE)
    b = selector.select(snapshot(items), items, expected_suite_digest=SUITE)
    assert a.digest == b.digest
    with pytest.raises(GenerationSelectionError):
        selector.select(snapshot(items), items, expected_suite_digest=SUITE, hold_active=True)


def test_parameter_merge_requires_local_compatible_parent_descriptors():
    item = candidate("c1", 1, .9)
    report = EvolutionaryGenerationSelector().select(
        snapshot([item]), [item], expected_suite_digest=SUITE)
    assert report.selections[0].merge_strategy is MergeStrategy.PARAMETER
    nonlocal_parent = parent("p2", hashlib.sha256(b"p2").hexdigest(), local=False)
    item = CandidateModelEvidence(item.entry, (item.parent_descriptors[0], nonlocal_parent))
    report = EvolutionaryGenerationSelector().select(
        snapshot([item]), [item], expected_suite_digest=SUITE)
    assert report.selections[0].merge_strategy is MergeStrategy.ORCHESTRATION
